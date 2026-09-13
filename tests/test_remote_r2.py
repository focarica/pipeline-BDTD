from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from remote.r2 import R2ConfigError, build_client, sync_directory


def _not_found(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, operation)


class _FakeR2Client:
    """Cliente S3 falso, o suficiente para exercitar sync_directory sem rede."""

    def __init__(self, existing: dict[str, int] | None = None) -> None:
        self.existing = existing or {}
        self.uploaded: dict[str, str] = {}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.existing:
            raise _not_found("HeadObject")
        return {"ContentLength": self.existing[Key]}

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None:
        self.uploaded[Key] = Filename
        self.existing[Key] = Path(Filename).stat().st_size


def test_sync_directory_uploads_new_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("conteudo a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("conteudo b", encoding="utf-8")

    client = _FakeR2Client()
    report = sync_directory(client, tmp_path, "meu-bucket", "raw", log=lambda _msg: None)

    assert report.ok
    assert set(report.uploaded) == {"raw/a.txt", "raw/sub/b.txt"}
    assert report.skipped == ()
    assert client.uploaded["raw/a.txt"] == str(tmp_path / "a.txt")


def test_sync_directory_skips_unchanged_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("conteudo a", encoding="utf-8")
    size = (tmp_path / "a.txt").stat().st_size

    client = _FakeR2Client(existing={"raw/a.txt": size})
    report = sync_directory(client, tmp_path, "meu-bucket", "raw", log=lambda _msg: None)

    assert report.ok
    assert report.uploaded == ()
    assert report.skipped == ("raw/a.txt",)


def test_sync_directory_reuploads_changed_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("conteudo bem maior que antes", encoding="utf-8")

    client = _FakeR2Client(existing={"raw/a.txt": 1})
    report = sync_directory(client, tmp_path, "meu-bucket", "raw", log=lambda _msg: None)

    assert report.uploaded == ("raw/a.txt",)
    assert report.skipped == ()


def test_sync_directory_missing_local_root(tmp_path: Path) -> None:
    client = _FakeR2Client()
    with pytest.raises(RuntimeError):
        sync_directory(client, tmp_path / "nao-existe", "meu-bucket", "raw", log=lambda _msg: None)


def test_build_client_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # load_dotenv() sem argumentos localiza o .env a partir do arquivo que o
    # chama (inspeção de call stack), não do cwd — então um .env real do
    # projeto vazaria credenciais aqui se não isolarmos a chamada.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(R2ConfigError):
        build_client()


def test_build_client_builds_with_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("R2_ACCOUNT_ID", "conta123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "chave")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "segredo")

    client = build_client()

    assert client.meta.endpoint_url == "https://conta123.r2.cloudflarestorage.com"
