from __future__ import annotations

from pathlib import Path

import pytest

import main
import remote.r2 as r2


class _FakeReport:
    ok = True
    uploaded: tuple[str, ...] = ()
    skipped = ("curated/chunks.jsonl",)
    failed: tuple[str, ...] = ()


def _fake_curated_dir(tmp_path: Path) -> Path:
    curated_dir = tmp_path / "curated_data"
    curated_dir.mkdir()
    (curated_dir / "chunks.jsonl").write_text("{}", encoding="utf-8")
    return curated_dir


def _no_op_load_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Impede que um .env real do projeto vaze credenciais para o teste.

    load_dotenv() sem argumentos localiza o arquivo a partir do módulo que o
    chama (inspeção de call stack), não do cwd — por isso monkeypatch.chdir
    não isola o teste sozinho; é preciso neutralizar a própria chamada.
    """
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)


def test_run_sync_reads_bucket_set_before_load_dotenv_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regressão: o bucket só disponível via .env deve ser lido ANTES do
    cheque de `--bucket`/`R2_BUCKET`, não depois."""
    monkeypatch.delenv("R2_BUCKET", raising=False)

    def _fake_load_dotenv(*args: object, **kwargs: object) -> bool:
        import os

        os.environ["R2_BUCKET"] = "bucket-do-dotenv"
        return True

    monkeypatch.setattr("dotenv.load_dotenv", _fake_load_dotenv)
    monkeypatch.setattr(r2, "build_client", lambda: object())

    captured: dict[str, str] = {}

    def _fake_sync_directory(_client, _local_root, bucket, _prefix, **_kwargs):
        captured["bucket"] = bucket
        return _FakeReport()

    monkeypatch.setattr(r2, "sync_directory", _fake_sync_directory)

    curated_dir = _fake_curated_dir(tmp_path)
    exit_code = main.main(["sync", "--layer", "curated", "--curated-dir", str(curated_dir)])

    assert exit_code == 0
    assert captured["bucket"] == "bucket-do-dotenv"


def test_run_sync_fails_without_bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R2_BUCKET", raising=False)
    _no_op_load_dotenv(monkeypatch)

    curated_dir = _fake_curated_dir(tmp_path)
    exit_code = main.main(["sync", "--layer", "curated", "--curated-dir", str(curated_dir)])

    assert exit_code == 1


def test_run_sync_prefers_explicit_bucket_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("R2_BUCKET", "bucket-do-ambiente")
    _no_op_load_dotenv(monkeypatch)
    curated_dir = _fake_curated_dir(tmp_path)

    captured: dict[str, str] = {}

    def _fake_sync_directory(_client, _local_root, bucket, _prefix, **_kwargs):
        captured["bucket"] = bucket
        return _FakeReport()

    monkeypatch.setattr(r2, "build_client", lambda: object())
    monkeypatch.setattr(r2, "sync_directory", _fake_sync_directory)

    exit_code = main.main(
        [
            "sync",
            "--layer",
            "curated",
            "--curated-dir",
            str(curated_dir),
            "--bucket",
            "bucket-explicito",
        ]
    )

    assert exit_code == 0
    assert captured["bucket"] == "bucket-explicito"
