import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("hybrid_search", Path(__file__).resolve().parents[1] / "hybrid_search.py")
hybrid = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hybrid)


class HybridTests(unittest.TestCase):
    def test_download_from_r2_records_hash_and_conditional_read(self):
        raw = b'{"chunk_id":"x"}\n'
        now = datetime.now(timezone.utc)
        class Client:
            def head_object(self, **kwargs):
                return {"ETag": '"etag"'}
            def get_object(self, **kwargs):
                self.kwargs = kwargs
                return {"Body": io.BytesIO(raw), "ContentLength": len(raw),
                        "ETag": '"etag"', "LastModified": now}
        client = Client()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "remote.jsonl"
            source = hybrid.download(client, "bucket", "curated/datasets/chunks.jsonl", path)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(source["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(client.kwargs["IfMatch"], '"etag"')

    def test_entries_preserve_source_and_abstract_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.jsonl"
            rows = [dict(chunk_id=f"d-{i}", bdtd_id="d", text=f"Texto {i}", title="Título",
                         abstract="Resumo", source_url="https://example.org/tese") for i in range(2)]
            path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            self.assertEqual(hybrid.validate_corpus(path), dict(chunks=2, documents=1, abstracts=1))
            entries = list(hybrid.entries(path))
            self.assertEqual(len(entries), 3)
            self.assertEqual(entries[1]["chunk_id"], "d::abstract")
            self.assertEqual(entries[1]["source_url"], "https://example.org/tese")

    def test_duplicate_ids_rejected_before_indexing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.jsonl"
            row = dict(chunk_id="same", bdtd_id="d", text="Texto")
            path.write_text((json.dumps(row) + "\n") * 2, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicado"):
                hybrid.validate_corpus(path)

    def test_nonfinite_embeddings_rejected(self):
        with patch.object(hybrid, "http", return_value={"embeddings": [[float("nan")]]}):
            with self.assertRaises(ValueError):
                hybrid.embed("ollama", hybrid.EMBEDDING_MODEL, ["texto"])

    def test_uuid_stable_and_kind_separates_ids(self):
        entry = dict(chunk_id="x", text="text", title="title", kind="chunk")
        self.assertEqual(hybrid.point(entry, [1])["id"], hybrid.point(entry, [2])["id"])
        self.assertNotEqual(hybrid.point(entry, [1])["id"], hybrid.point({**entry, "kind": "abstract"}, [1])["id"])

    def test_existing_collection_never_recreated(self):
        args = argparse.Namespace(qdrant="q", collection="existing")
        with patch.object(hybrid, "http", return_value={"result": {"collections": [{"name": "existing"}]}}) as call:
            with self.assertRaisesRegex(ValueError, "já existe"):
                hybrid.index(args)
            self.assertEqual(call.call_count, 1)

    def test_index_marks_complete_only_after_all_batches(self):
        args = argparse.Namespace(qdrant="q", ollama="o", collection="new",
                                  object_key="curated/datasets/chunks.jsonl", batch_size=1)
        states = []
        def download(client, bucket, key, path):
            path.write_text(json.dumps(dict(chunk_id="x", bdtd_id="d", text="Texto", abstract="Resumo")), encoding="utf-8")
            return {"sha256": "test"}
        def http(url, path, payload=None, method=None):
            if path == "/collections":
                return {"result": {"collections": []}}
            if payload and "points" in payload:
                for point in payload["points"]:
                    if point["id"] == hybrid.MANIFEST_ID:
                        states.append(point["payload"]["status"])
                    else:
                        self.assertEqual(states[-1], "building")
            return {}
        with patch.dict("os.environ", {"R2_BUCKET": "remote-bucket"}), patch.object(hybrid, "r2_client"), patch.object(hybrid, "download", side_effect=download), patch.object(hybrid, "embedding_identity", return_value={"name": hybrid.EMBEDDING_MODEL, "digest": "test"}) as identity, patch.object(hybrid, "embed", side_effect=lambda url, model, texts: [[1, 0] for text in texts]), patch.object(hybrid, "http", side_effect=http), redirect_stdout(io.StringIO()):
            hybrid.index(args)
        identity.assert_called_with("o", hybrid.EMBEDDING_MODEL)
        self.assertEqual(states, ["building", "complete"])

    def test_incomplete_collection_not_queried(self):
        args = argparse.Namespace(qdrant="q", ollama="o", collection="partial", text="question", limit=5)
        with patch.object(hybrid, "http", return_value={"result": {"payload": {"status": "building"}}}):
            with self.assertRaisesRegex(ValueError, "incompleta"):
                hybrid.query(args)

    def test_old_index_is_rejected_without_embedding(self):
        manifest = {"status": "complete", "embedding": {"name": "bge-m3:latest"}}
        with patch.object(hybrid, "http", return_value={"result": {"payload": manifest}}), patch.object(hybrid, "embed") as embed:
            with self.assertRaisesRegex(ValueError, "reindexe"):
                hybrid.search_points("q", "o", "c", "pergunta", 5)
            embed.assert_not_called()

    def test_search_points_use_dense_qdrant_collection(self):
        metadata = {"status": "complete", "source": {"sha256": "corpus"},
                    "embedding": {"name": hybrid.EMBEDDING_MODEL, "digest": "d", "dimensions": 2}}
        calls = []
        def fake_http(url, path, payload=None, method=None):
            calls.append((url, path, payload, method))
            if path.endswith(hybrid.MANIFEST_ID):
                return {"result": {"payload": metadata}}
            return {"result": {"points": [{"id": "point-1", "payload": {"chunk_id": "c1"}}]}}
        with patch.object(hybrid, "http", side_effect=fake_http), patch.object(hybrid, "embedding_identity", return_value={"name": hybrid.EMBEDDING_MODEL, "digest": "d"}), patch.object(hybrid, "embed", return_value=[[1, 0]]) as embed:
            got_metadata, points = hybrid.search_points("q", "o", "c", "minha pergunta", 5)
            self.assertIs(got_metadata, metadata)
            self.assertEqual(points[0]["payload"]["chunk_id"], "c1")
            self.assertEqual(calls[-1][2], {"query": [1, 0], "using": "dense", "limit": 5, "with_payload": True})
            self.assertTrue(embed.call_args.args[2][0].endswith("\nQuery: minha pergunta"))

    def test_semantic_search_fails_if_embedding_digest_changed(self):
        manifest = {"status": "complete", "source": {},
                    "embedding": {"name": hybrid.EMBEDDING_MODEL, "digest": "old", "dimensions": 2}}
        with patch.object(hybrid, "http", return_value={"result": {"payload": manifest}}), patch.object(hybrid, "embedding_identity", return_value={"name": hybrid.EMBEDDING_MODEL, "digest": "new"}):
            with self.assertRaisesRegex(ValueError, "difere"):
                hybrid.search_points("q", "o", "c", "pergunta", 5)


if __name__ == "__main__":
    unittest.main()
