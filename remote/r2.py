"""Sincronização de camadas locais com um bucket R2 da Cloudflare.

R2 é compatível com a API do S3, então usamos o `boto3` normal apontando
para o endpoint da Cloudflare. As credenciais nunca ficam no código: vêm de
variáveis de ambiente (opcionalmente carregadas de um arquivo `.env` local,
que nunca deve ser commitado).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import dotenv

_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class R2ConfigError(RuntimeError):
    """Erro de configuração das credenciais ou do bucket do R2."""


@dataclass(frozen=True)
class SyncReport:
    uploaded: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()

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
) -> SyncReport:
    """Envia todo arquivo de ``local_root`` para ``bucket/prefix``.

    Um arquivo é pulado quando já existe um objeto remoto do mesmo tamanho
    no mesmo caminho — heurística barata (evita um download só para
    conferir hash) que funciona bem aqui porque as camadas do pipeline não
    editam arquivos já escritos, só os regeneram por inteiro.
    """
    local_root = Path(local_root)
    if not local_root.exists():
        raise RuntimeError(f"diretório local não encontrado: {local_root}")

    files = sorted(path for path in local_root.rglob("*") if path.is_file())
    log(f"sincronizando {len(files)} arquivos de {local_root} para s3://{bucket}/{prefix}")

    uploaded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for path in files:
        relative = path.relative_to(local_root).as_posix()
        key = f"{prefix.rstrip('/')}/{relative}" if prefix else relative
        try:
            local_size = path.stat().st_size
            if _remote_size(client, bucket, key) == local_size:
                skipped.append(key)
                continue
            client.upload_file(str(path), bucket, key)
            uploaded.append(key)
            log(f"enviado: {key}")
        except (ClientError, OSError) as exc:
            failed.append(key)
            log(f"falha ao enviar {key}: {exc}")

    log(
        f"sincronização concluída: {len(uploaded)} enviados, {len(skipped)} já "
        f"atualizados, {len(failed)} falharam"
    )
    return SyncReport(uploaded=tuple(uploaded), skipped=tuple(skipped), failed=tuple(failed))


def _remote_size(client: Any, bucket: str, key: str) -> int | None:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _NOT_FOUND_CODES:
            return None
        raise
    return response.get("ContentLength")
