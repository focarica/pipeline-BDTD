"""Migracao R2 (Cloudflare) -> Shared Drive com deduplicacao.

Lista objetos do R2, baixa temporariamente e re-envia ao Drive usando
a mesma logica de dedup por sha256 de remote/drive.py.
Nao afeta o local data/raw — e transferencia direta entre nuvens.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import time
from typing import Any

import dotenv

from .drive import DriveConfigError, DriveSyncReport, _ensure_prefix, _list_remote_tree, build_drive_client
from .r2 import R2ConfigError, build_client as build_r2_client

_LIST_PAGE_SIZE = 1000


@dataclass
class MigrateReport:
    uploaded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    duplicate: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed


def migrate_r2_to_drive(
    *,
    bucket: str,
    prefix: str,
    folder_id: str,
    shared_drive_id: str | None = None,
    max_workers: int = 4,
    dry_run: bool = False,
    tmp_dir: str | Path | None = None,
    log=print,
) -> MigrateReport:
    dotenv.load_dotenv()
    # build clients
    try:
        r2 = build_r2_client()
    except R2ConfigError as exc:
        raise RuntimeError(f"R2: {exc}") from exc
    try:
        drive = build_drive_client()
    except DriveConfigError as exc:
        raise RuntimeError(f"Drive: {exc}") from exc

    # index Drive para dedup
    target_folder_id = _ensure_prefix(drive, folder_id, prefix.strip("/"), log, shared_drive_id)
    remote_by_path, remote_by_hash, _ = _list_remote_tree(drive, target_folder_id, log, shared_drive_id)

    # lista R2
    r2_keys = _list_r2_keys(r2, bucket, prefix.strip("/") + "/" if prefix.strip("/") else "", log)
    log(f"{len(r2_keys)} objetos no R2 em s3://{bucket}/{prefix}")

    # filtra ja existentes por path (evita download)
    to_fetch: list[str] = []
    skipped: list[str] = []
    duplicate: list[str] = []
    # precisamos do sha dos objetos R2 para dedup preciso — sem head com sha,
    # vamos baixar e calcular hash; mas se key ja existe no Drive por path+hash
    # e tamanho nao temos tamanho R2 aqui, entao consideramos fetch
    # Otimizacao: se key rel ja em remote_by_path, pular download e marcar skipped
    # (assumindo R2 e Drive ja sincronizados por path). Para rigor, baixamos e
    # conferimos sha.
    for key in r2_keys:
        rel = key[len(prefix.strip("/") + "/") :] if prefix.strip("/") else key
        if rel in remote_by_path and not dry_run:
            # ainda precisa verificar hash — vamos baixar para conferir dedup real
            # mas se quisermos economizar banda, poderiamos pular. Aqui baixamos
            # para garantir dedup por conteudo.
            pass
        to_fetch.append(key)

    if dry_run:
        return MigrateReport(uploaded=(), skipped=tuple(sorted(skipped)), duplicate=(), failed=())

    # baixa + re-upload com dedup
    tmp_root = Path(tmp_dir) if tmp_dir else Path(tempfile.mkdtemp(prefix="bdtd-migrate-"))
    tmp_root.mkdir(parents=True, exist_ok=True)

    uploaded: list[str] = []
    failed: list[str] = []
    # sequencial para simplicidade + dedup incremental; paraleliza download+upload por key
    # Usa pool mas atualiza remote_by_hash compartilhado sob lock simples via
    # retorno ordenado

    def _one(key: str) -> tuple[str, str, str]:
        rel = key[len(prefix.strip("/") + "/") :] if prefix.strip("/") else key
        local_tmp = tmp_root / rel
        local_tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            # download R2
            r2.download_file(bucket, key, str(local_tmp))
        except Exception as exc:
            return ("failed", rel, f"download R2: {exc}")
        # hash
        h = hashlib.sha256()
        with local_tmp.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        sha = h.hexdigest()
        if sha in remote_by_hash:
            # dedup global
            try:
                local_tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return ("duplicate", rel, remote_by_hash[sha])
        # upload Drive (reusa logica de drive sem recalcular hash)
        from .drive import _upload_one

        status, _, err, _ = _upload_one(drive, target_folder_id, local_tmp, rel, sha, log, shared_drive_id)
        try:
            local_tmp.unlink(missing_ok=True)
        except OSError:
            pass
        if status == "uploaded":
            return ("uploaded", rel, sha)
        if status == "duplicate":
            return ("duplicate", rel, err)
        if status == "failed":
            return ("failed", rel, err)
        return (status, rel, err)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        results = list(pool.map(_one, to_fetch))

    for status, rel, info in results:
        if status == "uploaded":
            uploaded.append(rel)
            # atualiza hash para dedup dentro do lote
            # info contem sha
            remote_by_hash[info] = rel
        elif status == "duplicate":
            duplicate.append(rel)
        elif status == "failed":
            failed.append(rel)
            log(f"falha migrar {rel}: {info}")
        elif status == "skipped":
            skipped.append(rel)

    # limpeza tmp se criado automaticamente
    if tmp_dir is None:
        try:
            import shutil

            shutil.rmtree(tmp_root, ignore_errors=True)
        except OSError:
            pass

    return MigrateReport(
        uploaded=tuple(sorted(uploaded)),
        skipped=tuple(sorted(skipped)),
        duplicate=tuple(sorted(duplicate)),
        failed=tuple(sorted(failed)),
    )


def _list_r2_keys(r2: Any, bucket: str, prefix: str, log) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": _LIST_PAGE_SIZE}
        if token:
            kwargs["ContinuationToken"] = token
        resp = r2.list_objects_v2(**kwargs)
        for item in resp.get("Contents", []):
            k = item.get("Key")
            if isinstance(k, str):
                keys.append(k)
        token = resp.get("NextContinuationToken")
        if not resp.get("IsTruncated") or not token:
            break
    return keys
