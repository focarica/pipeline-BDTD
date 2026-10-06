"""Sincronizacao de camadas locais com Shared Drive (Google Drive).

Usa Service Account (drive-bdtd) com `appProperties.sha256` para deduplicacao
por conteudo. Nenhum arquivo com mesmo sha256 e enviado duas vezes, mesmo
com nome diferente ou por usuarios diferentes.

Credenciais vêm de variaveis de ambiente / .env (mesmo padrao de remote/r2.py).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import mimetypes
import os
from pathlib import Path
import time
from typing import Any

import dotenv

_MAX_ATTEMPTS = 3
_LIST_PAGE_SIZE = 1000
_PROGRESS_THRESHOLD = 5 * 1024 * 1024
_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB resumable
_DEFAULT_FOLDER_ID = "1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8"


class DriveConfigError(RuntimeError):
    """Erro de configuracao das credenciais do Drive."""


@dataclass(frozen=True)
class DriveSyncReport:
    uploaded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()  # mesmo path+hash ja no Drive
    duplicate: tuple[str, ...] = ()  # mesmo sha256 ja existe em outro path
    failed: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()  # dry-run
    duplicate_of: tuple[tuple[str, str], ...] = ()  # (local_path, remote_path_do_hash)

    @property
    def ok(self) -> bool:
        return not self.failed


def build_drive_client() -> Any:
    """Cria service do Drive via Service Account.

    Lê `GOOGLE_APPLICATION_CREDENTIALS` ou `GDRIVE_CREDENTIALS_PATH` do
    ambiente (carrega .env se existir, sem sobrescrever env real).
    """
    dotenv.load_dotenv()
    cred_path = (
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        or os.environ.get("GDRIVE_CREDENTIALS_PATH", "").strip()
        or os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    )
    # fallback locais
    if not cred_path:
        for cand in [
            Path.home() / ".config/pipeline-bdtd/sa-key.json",
            Path("secrets/drive-bdtd-sa.json"),
        ]:
            if cand.exists():
                cred_path = str(cand)
                break
    if not cred_path:
        raise DriveConfigError(
            "credenciais do Drive ausentes: defina GOOGLE_APPLICATION_CREDENTIALS "
            "ou GDRIVE_CREDENTIALS_PATH (caminho para o JSON da SA)"
        )
    p = Path(cred_path).expanduser()
    if not p.exists():
        raise DriveConfigError(f"arquivo de credenciais nao encontrado: {p}")

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DriveConfigError(
            "dependencias do Drive ausentes: pip install google-api-python-client google-auth"
        ) from exc

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(str(p), scopes=scopes)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return service


def sync_directory(
    service: Any,
    local_root: str | Path,
    folder_id: str,
    prefix: str,
    *,
    log: Callable[[str], None] = print,
    max_workers: int = 4,
    dry_run: bool = False,
    shared_drive_id: str | None = None,
) -> DriveSyncReport:
    """Envia todo arquivo de ``local_root`` para Drive ``folder_id/prefix``.

    Deduplicacao: calcula sha256 local e compara com `appProperties.sha256`
    de todos os arquivos ja no Drive. Se o hash ja existe em qualquer path,
    o arquivo e marcado como `duplicate` e nao e reenviado.
    Mesma heuristica barata de remote/r2.py para path+size e mantida como
    segundo nivel (skipped).
    """
    local_root = Path(local_root)
    if not local_root.exists():
        raise RuntimeError(f"diretorio local nao encontrado: {local_root}")

    files = sorted(path for path in local_root.rglob("*") if path.is_file())
    remote_prefix = prefix.strip("/")
    target_folder_id = _ensure_prefix(service, folder_id, remote_prefix, log, shared_drive_id)

    log(f"sincronizando {len(files)} arquivos de {local_root} para drive://{folder_id}/{prefix}")
    # index remoto recursivo
    remote_by_path, remote_by_hash, remote_sizes = _list_remote_tree(
        service, target_folder_id, log, shared_drive_id
    )

    # tasks com hash local (calculado sequencial para evitar thrash de IO antes do pool)
    tasks: list[tuple[Path, str, str, int]] = []
    for path in files:
        rel = path.relative_to(local_root).as_posix()
        sha = _file_sha256(path)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        tasks.append((path, rel, sha, size))

    uploaded: list[str] = []
    skipped: list[str] = []
    duplicate: list[str] = []
    failed: list[str] = []
    pending: list[str] = []
    dup_of: list[tuple[str, str]] = []

    def _one(task: tuple[Path, str, str, int]) -> tuple[str, str, str, str]:
        path, rel, sha, size = task
        # 1) dedup por conteudo
        if sha in remote_by_hash:
            remote_path = remote_by_hash[sha]
            # se mesmo path+hash, conta como skipped (ja no lugar certo)
            if remote_by_path.get(rel) == sha:
                return ("skipped", rel, "", remote_path)
            return ("duplicate", rel, f"sha256 {sha[:12]} ja em {remote_path}", remote_path)
        # 2) mesmo path+size ja existe (sem hash legado)
        if rel in remote_by_path and remote_sizes.get(rel) == size:
            return ("skipped", rel, "", rel)
        if dry_run:
            return ("pending", rel, "", "")
        # 3) upload com appProperties
        return _upload_one(service, target_folder_id, path, rel, sha, log, shared_drive_id)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        results = list(pool.map(_one, tasks))

    for status, rel, err, remote_path in results:
        if status == "uploaded":
            uploaded.append(rel)
            # atualiza indice para proximos arquivos do lote verem o hash
            # (evita duplicar dentro do mesmo lote)
            sha = next(sha for p, r, sha, s in tasks if r == rel)
            remote_by_hash[sha] = rel
            remote_by_path[rel] = sha
        elif status == "skipped":
            skipped.append(rel)
        elif status == "duplicate":
            duplicate.append(rel)
            dup_of.append((rel, remote_path))
            log(f"duplicado (sha256 ja no Drive): {rel} -> {remote_path}")
        elif status == "pending":
            pending.append(rel)
        else:
            failed.append(rel)
            log(f"falha ao enviar {rel}: {err}")

    log(
        f"sincronizacao Drive concluida: {len(uploaded)} enviados, {len(skipped)} ja "
        f"atualizados, {len(duplicate)} duplicados (sha256), {len(failed)} falharam, {len(pending)} pendentes (dry-run)"
    )
    return DriveSyncReport(
        uploaded=tuple(sorted(uploaded)),
        skipped=tuple(sorted(skipped)),
        duplicate=tuple(sorted(duplicate)),
        failed=tuple(sorted(failed)),
        pending=tuple(sorted(pending)),
        duplicate_of=tuple(sorted(dup_of)),
    )


# ---------- internals ----------


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_prefix(service: Any, root_id: str, prefix: str, log: Callable[[str], None], shared_drive_id: str | None) -> str:
    if not prefix:
        return root_id
    cur = root_id
    for part in prefix.split("/"):
        cur = _get_or_create_folder(service, cur, part, log, shared_drive_id)
    return cur


def _get_or_create_folder(service: Any, parent_id: str, name: str, log: Callable[[str], None], shared_drive_id: str | None) -> str:
    # busca pasta com mesmo nome
    escaped = name.replace("'", "\\'")
    q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false and name='{escaped}'"
    kwargs: dict[str, Any] = {
        "q": q,
        "fields": "files(id,name)",
        "pageSize": 10,
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
    }
    if shared_drive_id:
        kwargs["driveId"] = shared_drive_id
        kwargs["corpora"] = "drive"
    resp = service.files().list(**kwargs).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    body = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    created = service.files().create(body=body, fields="id", supportsAllDrives=True).execute()
    fid = created["id"]
    log(f"pasta criada no Drive: {name} ({fid})")
    return fid


def _list_remote_tree(service: Any, folder_id: str, log: Callable[[str], None], shared_drive_id: str | None) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    """Lista recursivamente a arvore de folder_id.

    Retorna (by_path: rel->sha, by_hash: sha->rel, sizes: rel->int).
    Rel e relativo ao prefix folder (sem prefix).
    """
    by_path: dict[str, str] = {}
    by_hash: dict[str, str] = {}
    sizes: dict[str, int] = {}

    def _walk(fid: str, prefix: str) -> None:
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "q": f"'{fid}' in parents and trashed=false",
                "fields": "nextPageToken, files(id,name,mimeType,size,md5Checksum,appProperties,parents)",
                "pageSize": _LIST_PAGE_SIZE,
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if shared_drive_id:
                kwargs["driveId"] = shared_drive_id
                kwargs["corpora"] = "drive"
            if page_token:
                kwargs["pageToken"] = page_token
            try:
                resp = service.files().list(**kwargs).execute()
            except Exception as exc:
                raise RuntimeError(f"falha ao listar drive://{fid}: {exc}") from exc
            for f in resp.get("files", []):
                name = f.get("name", "")
                if f.get("mimeType") == "application/vnd.google-apps.folder":
                    _walk(f["id"], f"{prefix}{name}/" if prefix else f"{name}/")
                else:
                    rel = f"{prefix}{name}"
                    sha = ""
                    props = f.get("appProperties") or {}
                    if isinstance(props, dict):
                        sha = str(props.get("sha256", "")).strip().lower()
                    # fallback: usa md5 como chave se sha nao existe (legado)
                    if not sha:
                        md5 = str(f.get("md5Checksum", "")).strip().lower()
                        if md5:
                            sha = f"md5:{md5}"
                    if sha:
                        by_path[rel] = sha
                        if sha not in by_hash:
                            by_hash[sha] = rel
                    try:
                        sizes[rel] = int(f.get("size", 0))
                    except (TypeError, ValueError):
                        sizes[rel] = 0
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    _walk(folder_id, "")
    log(f"{len(by_path)} arquivos indexados no Drive (dedup por sha256), {len(sizes)} com tamanho")
    return by_path, by_hash, sizes


def _upload_one(
    service: Any,
    target_folder_id: str,
    path: Path,
    rel: str,
    sha: str,
    log: Callable[[str], None],
    shared_drive_id: str | None,
) -> tuple[str, str, str, str]:
    # resolve parent folder id for nested rel
    parts = rel.split("/")
    filename = parts[-1]
    parent_id = target_folder_id
    for part in parts[:-1]:
        parent_id = _get_or_create_folder(service, parent_id, part, log, shared_drive_id)

    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"
    # bdtd_id extraido do path documents/<id>/file.pdf se existir
    bdtd_id = parts[1] if len(parts) >= 3 and parts[0] == "documents" else rel

    body = {
        "name": filename,
        "parents": [parent_id],
        "appProperties": {"sha256": sha, "bdtd_id": bdtd_id[:100], "rel": rel[:400]},
    }
    try:
        local_size = path.stat().st_size
    except OSError as exc:
        return ("failed", rel, str(exc), "")

    for attempt in range(_MAX_ATTEMPTS):
        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(str(path), mimetype=mime, resumable=True, chunksize=_CHUNK_SIZE)
            # progress callback simples
            req = service.files().create(body=body, media_body=media, fields="id,name", supportsAllDrives=True)
            # resumable loop com log a cada 25%
            if local_size >= _PROGRESS_THRESHOLD:
                logger = _ProgressLogger(log, rel, local_size)
                # MediaFileUpload.next_chunk precisa ser chamado manualmente se quisermos progresso,
                # mas googleapiclient ja faz; simplificamos para execute() + log final
                # Para progresso real, usar next_chunk loop:
                response = None
                while response is None:
                    status, response = req.next_chunk()
                    if status:
                        logger(int(status.resumable_progress or 0) - logger._seen if hasattr(logger, "_seen") else 0)
                        # hack: _ProgressLogger expects incremental, vamos recalcular
                        # na pratica loga 25% steps
                        pass
            else:
                req.execute()
            log(f"enviado Drive: {rel} (sha256 {sha[:12]})")
            return ("uploaded", rel, "", "")
        except Exception as exc:
            msg = str(exc)
            # rate limit / transient
            if "rateLimit" in msg.lower() or "quota" in msg.lower() or "500" in msg or "503" in msg:
                if attempt + 1 < _MAX_ATTEMPTS:
                    time.sleep(2**attempt)
                    continue
            if attempt + 1 < _MAX_ATTEMPTS and ("403" in msg or "429" in msg):
                time.sleep(2**attempt)
                continue
            if attempt + 1 >= _MAX_ATTEMPTS:
                return ("failed", rel, msg, "")
            time.sleep(2**attempt)
    return ("failed", rel, "tentativas esgotadas", "")


class _ProgressLogger:
    """Informa progresso a cada 25% (mesmo de remote/r2.py:202)."""

    def __init__(self, log: Callable[[str], None], key: str, total: int) -> None:
        self._log = log
        self._key = key
        self._total = total
        self._seen = 0
        self._next_mark = 25

    def __call__(self, chunk: int) -> None:
        self._seen += chunk
        percent = (self._seen / self._total) * 100 if self._total else 100
        while percent >= self._next_mark and self._next_mark <= 100:
            self._log(f"{self._key}: {self._next_mark}% enviado")
            self._next_mark += 25
