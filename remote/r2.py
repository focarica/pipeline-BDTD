"""Sincronização de camadas locais com um bucket R2 da Cloudflare.

R2 é compatível com a API do S3, então usamos o `boto3` normal apontando
para o endpoint da Cloudflare. As credenciais nunca ficam no código: vêm de
variáveis de ambiente (opcionalmente carregadas de um arquivo `.env` local,
que nunca deve ser commitado).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import dotenv

_MAX_ATTEMPTS = 2
_LIST_PAGE_SIZE = 1000
_PROGRESS_THRESHOLD = 5 * 1024 * 1024


class R2ConfigError(RuntimeError):
    """Erro de configuração das credenciais ou do bucket do R2."""


@dataclass(frozen=True)
class SyncReport:
    uploaded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed


def build_client() -> Any:
    """Cria um cliente S3 apontando para o endpoint do R2.

    Lê `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY` do
    ambiente (carregando um `.env` na raiz do projeto, se existir, sem
    sobrescrever variáveis já definidas no ambiente real).
    """
    dotenv.load_dotenv()
    account_id = os.environ.get("R2_ACCOUNT_ID", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    missing = [
        name
        for name, value in (
            ("R2_ACCOUNT_ID", account_id),
            ("R2_ACCESS_KEY_ID", access_key),
            ("R2_SECRET_ACCESS_KEY", secret_key),
        )
        if not value
    ]
    if missing:
        raise R2ConfigError(
            "variáveis de ambiente ausentes para o R2: " + ", ".join(missing)
        )

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def sync_directory(
    client: Any,
    local_root: str | Path,
    bucket: str,
    prefix: str,
    *,
    log: Callable[[str], None] = print,
    max_workers: int = 8,
    dry_run: bool = False,
) -> SyncReport:
    """Envia todo arquivo de ``local_root`` para ``bucket/prefix``.

    Um arquivo é pulado quando já existe um objeto remoto do mesmo tamanho
    no mesmo caminho — heurística barata (evita um download só para
    conferir hash) que funciona bem aqui porque as camadas do pipeline não
    editam arquivos já escritos, só os regeneram por inteiro.

    Os tamanhos remotos vêm de uma única listagem paginada do prefixo, e os
    uploads rodam em paralelo com até 2 tentativas por arquivo. Com
    ``dry_run=True`` nada é enviado: os arquivos diferentes entram em
    ``pending`` no relatório.
    """
    local_root = Path(local_root)
    if not local_root.exists():
        raise RuntimeError(f"diretório local não encontrado: {local_root}")

    files = sorted(path for path in local_root.rglob("*") if path.is_file())
    remote_prefix = f"{prefix.rstrip('/')}/" if prefix else ""
    log(f"sincronizando {len(files)} arquivos de {local_root} para s3://{bucket}/{prefix}")
    remote_sizes = _list_remote_sizes(client, bucket, remote_prefix, log)

    tasks = [
        (path, f"{remote_prefix}{path.relative_to(local_root).as_posix()}")
        for path in files
    ]
    uploaded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    pending: list[str] = []

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        results = pool.map(
            lambda task: _sync_one(client, bucket, task[1], task[0], remote_sizes.get(task[1]), dry_run, log),
            tasks,
        )
    for status, key, error in results:
        if status == "uploaded":
            uploaded.append(key)
        elif status == "skipped":
            skipped.append(key)
        elif status == "pending":
            pending.append(key)
        else:
            failed.append(key)
            log(f"falha ao enviar {key}: {error}")

    log(
        f"sincronização concluída: {len(uploaded)} enviados, {len(skipped)} já "
        f"atualizados, {len(failed)} falharam, {len(pending)} pendentes (dry-run)"
    )
    return SyncReport(
        uploaded=tuple(sorted(uploaded)),
        skipped=tuple(sorted(skipped)),
        failed=tuple(sorted(failed)),
        pending=tuple(sorted(pending)),
    )


def _list_remote_sizes(client: Any, bucket: str, prefix: str, log: Callable[[str], None]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": _LIST_PAGE_SIZE}
        if token:
            kwargs["ContinuationToken"] = token
        try:
            response = client.list_objects_v2(**kwargs)
        except ClientError as exc:
            raise RuntimeError(f"falha ao listar s3://{bucket}/{prefix}: {exc}") from exc
        for item in response.get("Contents", []):
            if isinstance(item.get("Key"), str):
                sizes[item["Key"]] = int(item.get("Size", 0))
        token = response.get("NextContinuationToken")
        if not response.get("IsTruncated") or not token:
            break
    log(f"{len(sizes)} objetos remotos encontrados em s3://{bucket}/{prefix}")
    return sizes


def _sync_one(
    client: Any,
    bucket: str,
    key: str,
    path: Path,
    remote_size: int | None,
    dry_run: bool,
    log: Callable[[str], None],
) -> tuple[str, str, str]:
    try:
        local_size = path.stat().st_size
    except OSError as exc:
        return ("failed", key, str(exc))
    if remote_size == local_size:
        return ("skipped", key, "")
    if dry_run:
        return ("pending", key, "")
    callback = _ProgressLogger(log, key, local_size) if local_size >= _PROGRESS_THRESHOLD else None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            if callback is not None:
                client.upload_file(str(path), bucket, key, Callback=callback)
            else:
                client.upload_file(str(path), bucket, key)
            log(f"enviado: {key}")
            return ("uploaded", key, "")
        except (ClientError, OSError) as exc:
            error = str(exc)
            if attempt + 1 < _MAX_ATTEMPTS:
                time.sleep(2**attempt)
    return ("failed", key, error)


class _ProgressLogger:
    """Informa o progresso de uploads grandes a cada 25% transferidos."""

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
