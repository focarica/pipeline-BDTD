# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.35,<2"]
# ///
"""Base híbrida Qdrant: curated do R2, embeddings Ollama e BM25 nativo."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

MANIFEST_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "bdtd-hybrid-index-manifest-v1"))


def http(base, path, payload=None, method=None):
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(base.rstrip("/") + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {exc.code} em {base}{path}: {detail}") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Falha em {base}{path}: {exc}") from exc


def check_server(url):
    info = http(url, "/")
    version = tuple(int(n) for n in info["version"].split(".")[:2])
    if version < (1, 20):
        raise ValueError("BM25 nativo exige Qdrant >= 1.20; use o compose.yaml deste projeto")


def embedding_identity(url, name):
    models = http(url, "/api/tags").get("models", [])
    for model in models:
        if model.get("name") in (name, name + ":latest"):
            return {"name": model["name"], "digest": model["digest"]}
    raise ValueError(f"Embedding {name!r} ausente no Ollama. Instale antes: ollama pull {name}")


def embed(url, model, texts):
    data = http(url, "/api/embed", {"model": model, "input": texts, "truncate": False})
    vectors = data.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise ValueError("Quantidade de embeddings incompatível com os textos enviados")
    size = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise ValueError("Embedding inválido")
        size = size or len(vector)
        if len(vector) != size or not any(vector):
            raise ValueError("Embedding com dimensão inconsistente ou vetor zero")
    return vectors


def r2_client():
    import boto3
    from botocore.config import Config
    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        if not os.environ.get(name, "").strip():
            raise ValueError(f"Variável ausente: {name}; use uv run --env-file /caminho/.env")
    return boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
        config=Config(signature_version="s3v4", connect_timeout=15, read_timeout=90,
                      retries={"mode": "standard", "total_max_attempts": 2}))


def download(client, bucket, key, destination):
    head = client.head_object(Bucket=bucket, Key=key)
    response = client.get_object(Bucket=bucket, Key=key, IfMatch=head["ETag"])
    digest, size = hashlib.sha256(), 0
    with response["Body"] as body, destination.open("wb") as output:
        for block in iter(lambda: body.read(1024 * 1024), b""):
            output.write(block)
            digest.update(block)
            size += len(block)
    if size != response["ContentLength"]:
        raise ValueError("Download incompleto; nenhuma coleção foi criada")
    return {"bucket": bucket, "object_key": key, "etag": response["ETag"],
            "version_id": response.get("VersionId"), "byte_count": size,
            "sha256": digest.hexdigest(), "last_modified": response["LastModified"].isoformat(),
            "retrieved_at": datetime.now(timezone.utc).isoformat()}


def records(path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("chunk_id", "bdtd_id", "text")):
                raise ValueError(f"Curated inválido na linha {number}: exige chunk_id, bdtd_id e text")
            for field in ("title", "abstract", "source_url", "section"):
                if row.get(field) is not None and not isinstance(row[field], str):
                    raise ValueError(f"Campo {field} inválido na linha {number}")
            yield row


def validate_corpus(path):
    ids, docs, abstracts = set(), set(), set()
    for row in records(path):
        if row["chunk_id"] in ids:
            raise ValueError(f"chunk_id duplicado: {row['chunk_id']}")
        ids.add(row["chunk_id"])
        docs.add(row["bdtd_id"])
        if row.get("abstract", "") and row["abstract"].strip():
            abstracts.add(row["bdtd_id"])
    if not ids:
        raise ValueError("Corpus remoto vazio")
    return {"chunks": len(ids), "documents": len(docs), "abstracts": len(abstracts)}


def entries(path):
    abstracts = set()
    for row in records(path):
        base = {key: row.get(key) for key in ("bdtd_id", "title", "source_url", "section")}
        yield {**base, "chunk_id": row["chunk_id"], "text": row["text"], "kind": "chunk"}
        doc = row["bdtd_id"]
        if doc not in abstracts and row.get("abstract") and row["abstract"].strip():
            abstracts.add(doc)
            yield {**base, "chunk_id": doc + "::abstract", "text": row["abstract"],
                   "section": "metadata.abstract", "kind": "abstract"}


def point(entry, vector):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "bdtd:" + entry["kind"] + ":" + entry["chunk_id"])),
            "vector": {"dense": vector},
            "payload": {**entry, "search_text": (entry.get("title") or "") + "\n" + entry["text"]}}


def save_manifest(args, metadata):
    http(args.qdrant, f"/collections/{args.collection}/points?wait=true",
         {"points": [{"id": MANIFEST_ID, "vector": {}, "payload": metadata}]}, "PUT")


def index(args):
    check_server(args.qdrant)
    if any(c["name"] == args.collection for c in http(args.qdrant, "/collections")["result"]["collections"]):
        raise ValueError("Coleção já existe; escolha um nome novo. Nada foi apagado ou sobrescrito.")
    identity = embedding_identity(args.ollama, args.embedding_model)
    # Snapshot temporário evita manter uma conexão R2 aberta durante horas de embeddings.
    with tempfile.TemporaryDirectory(prefix="bdtd-index-", dir="/tmp/opencode") as tmp:
        path = Path(tmp) / "curated.jsonl"
        print(f"Lendo s3://{os.environ.get('R2_BUCKET', '')}/{args.object_key}…", flush=True)
        source = download(r2_client(), os.environ["R2_BUCKET"], args.object_key, path)
        counts = validate_corpus(path)
        print(f"Snapshot R2 validado: {counts['documents']} documentos, {counts['chunks']} chunks; SHA-256 {source['sha256']}", flush=True)
        first = next(entries(path))
        dimensions = len(embed(args.ollama, identity["name"], [(first.get("title") or "") + "\n" + first["text"]])[0])
        http(args.qdrant, f"/collections/{args.collection}",
             {"vectors": {"dense": {"size": dimensions, "distance": "Cosine"}}}, "PUT")
        metadata = {"kind": "index_manifest", "status": "building", "source": source,
                    "counts": counts, "embedding": {**identity, "dimensions": dimensions}}
        save_manifest(args, metadata)
        http(args.qdrant, f"/collections/{args.collection}/index?wait=true", {
            "field_name": "search_text", "field_schema": {
                "type": "text", "tokenizer": "word", "lowercase": True,
                "ascii_folding": True, "stopwords": "portuguese", "scoring": True}}, "PUT")
        batch, uploaded = [], 0

        def flush():
            nonlocal uploaded
            vectors = embed(args.ollama, identity["name"], [(e.get("title") or "") + "\n" + e["text"] for e in batch])
            if any(len(v) != dimensions for v in vectors):
                raise ValueError("Modelo de embedding mudou de dimensão durante a carga")
            http(args.qdrant, f"/collections/{args.collection}/points?wait=true",
                 {"points": [point(e, v) for e, v in zip(batch, vectors)]}, "PUT")
            uploaded += len(batch)
            print(f"{uploaded}/{counts['chunks'] + counts['abstracts']} registros indexados", flush=True)
            batch.clear()

        for entry in entries(path):
            batch.append(entry)
            if len(batch) == args.batch_size:
                flush()
        if batch:
            flush()
        if embedding_identity(args.ollama, identity["name"]) != identity:
            raise ValueError("Modelo de embedding mudou durante a indexação; coleção não será liberada")
        metadata.update(status="complete", indexed_points=uploaded, completed_at=datetime.now(timezone.utc).isoformat())
        save_manifest(args, metadata)
        print(json.dumps(metadata, ensure_ascii=False, indent=2))


def query(args):
    check_server(args.qdrant)
    response = http(args.qdrant, f"/collections/{args.collection}/points/{MANIFEST_ID}")
    metadata = response["result"]["payload"]
    if metadata.get("status") != "complete":
        raise ValueError("Coleção incompleta; não está liberada para consulta")
    lexical = {"query": {"text": args.text}, "using": "search_text", "limit": max(20, args.limit)}
    if args.mode == "words":
        body = {**lexical, "limit": args.limit, "with_payload": True}
    else:
        identity = metadata["embedding"]
        current = embedding_identity(args.ollama, identity["name"])
        if current["digest"] != identity["digest"]:
            raise ValueError("Embedding instalado difere do usado no índice; restaure o modelo ou reindexe em outra coleção")
        vector = embed(args.ollama, identity["name"], [args.text])[0]
        if len(vector) != identity["dimensions"]:
            raise ValueError("Dimensão do embedding incompatível com o índice")
        dense = {"query": vector, "using": "dense", "limit": max(20, args.limit)}
        body = ({"prefetch": [lexical, dense], "query": {"fusion": "rrf"}}
                if args.mode == "hybrid" else dense)
        body.update(limit=args.limit, with_payload=True)
    result = http(args.qdrant, f"/collections/{args.collection}/points/query", body)
    print(json.dumps({"mode": args.mode, "source": metadata["source"],
                      "points": result["result"]["points"]}, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant", default="http://127.0.0.1:6333")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--collection", required=True, help="nome de coleção; index exige coleção nova")
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("index", help="indexa curated diretamente do R2, sem escrever no bucket")
    load.add_argument("--object-key", default="curated/datasets/chunks.jsonl")
    load.add_argument("--embedding-model", default="bge-m3")
    load.add_argument("--batch-size", type=int, default=8)
    search = sub.add_parser("query", help="recupera trechos; não chama modelo gerador")
    search.add_argument("--text", required=True)
    search.add_argument("--mode", choices=("hybrid", "words", "semantic"), default="hybrid")
    search.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.collection):
        parser.error("nome da coleção deve conter somente letras, números, _ ou -")
    if args.command == "index" and args.batch_size <= 0 or args.command == "query" and (args.limit <= 0 or not args.text.strip()):
        parser.error("lote/limite deve ser positivo e consulta não pode ser vazia")
    (index if args.command == "index" else query)(args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)
