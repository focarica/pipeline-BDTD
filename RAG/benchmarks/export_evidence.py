# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35,<2"]
# ///
"""Exporta somente evidências selecionadas do curated remoto (leitura apenas).

uv run --env-file /caminho/pipeline-BDTD/.env export_evidence.py
"""

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parent
DOCS = {
    "dust": ("csv_09029e92e5a17b06f0a70b1699ed875bd01cabe463405ad8a7d9ca86c7fbdec8", [0, 1, 35]),
    "persona": ("csv_09f387404ed4a4f564207ec7beb30046d692dbd5edd08d79527c0cc7f783c39a", [2, 50, 53]),
    "saal": ("csv_0bb74d9720951c01683741d6157c9acae3c4052873d0956395888a6d1965a094", [1]),
    "nutrition": ("UNIOESTE-1_5d299244327e069878702d38bd3ed462", [0, 41]),
    "stocks": ("UNIOESTE-1_25eeffbb8503efe67a07db1336ce2e2c", [0, 1, 32, 40, 41]),
    "covid": ("csv_07b66c97bdaa48f82a2354b0f340d1b9185183a45c00d2c5b8c104381281a68b", [0, 1]),
    "ecology": ("CRUZ_05d756b9b877ca76d077ba6eb52d9a31", [7, 30, 31]),
    "ata": ("IFAM-1_7008292e03badb1093e70eecaa3bd37c", [2]),
}


def main():
    out = ROOT / "evidence.json"
    if out.exists():
        raise FileExistsError("evidence.json já existe; preserve/versione o snapshot antes de substituí-lo")
    client = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
        config=Config(signature_version="s3v4", connect_timeout=15, read_timeout=90,
                      retries={"mode": "standard", "total_max_attempts": 2}),
    )
    bucket = os.environ["R2_BUCKET"]
    key = "curated/datasets/chunks.jsonl"
    response = client.get_object(Bucket=bucket, Key=key)
    wanted = {f"{doc}-chunk-{n:03d}": f"{alias}.{n:03d}"
              for alias, (doc, numbers) in DOCS.items() for n in numbers}
    aliases = {doc: alias for alias, (doc, _) in DOCS.items()}
    evidence, documents = {}, {}
    digest = hashlib.sha256()
    counts = Counter()
    buffer = b""

    def consume(line):
        if not line.strip():
            return
        row = json.loads(line)
        doc = row["bdtd_id"]
        counts[doc] += 1
        if doc in aliases and aliases[doc] not in documents:
            documents[aliases[doc]] = {k: row.get(k) for k in (
                "bdtd_id", "title", "abstract", "source_url", "date", "institution")}
        if row["chunk_id"] in wanted:
            evidence[wanted[row["chunk_id"]]] = {k: row.get(k) for k in (
                "chunk_id", "bdtd_id", "title", "section", "position", "text")}

    with response["Body"] as body:
        for block in iter(lambda: body.read(1024 * 1024), b""):
            digest.update(block)
            buffer += block
            lines = buffer.split(b"\n")
            buffer = lines.pop()
            for line in lines:
                consume(line)
        if buffer:
            consume(buffer)
    missing = sorted(set(wanted.values()) - evidence.keys())
    if missing:
        raise RuntimeError(f"Evidências ausentes; não gravando snapshot: {missing}")
    manifest_response = client.get_object(Bucket=bucket, Key="curated/manifests/curated.json")
    with manifest_response["Body"] as body:
        remote_manifest = json.loads(body.read())
    snapshot = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "object_key": key, "object_sha256": digest.hexdigest(),
        "object_last_modified": response["LastModified"].isoformat(),
        "actual_document_count": len(counts), "actual_chunk_count": sum(counts.values()),
        "remote_manifest": remote_manifest,
        "note": "page não exportado: a pipeline usa índice de seção, não página física do PDF.",
        "documents": documents, "evidence": evidence,
    }
    out = ROOT / "evidence.json"
    if out.exists():
        raise FileExistsError("evidence.json já existe; preserve/versione o snapshot antes de substituí-lo")
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(counts)} documentos, {sum(counts.values())} chunks; {len(evidence)} evidências selecionadas")
    print(f"SHA-256: {digest.hexdigest()}")


if __name__ == "__main__":
    main()
