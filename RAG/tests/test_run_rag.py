import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("run_rag", Path(__file__).resolve().parents[1] / "run_rag.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_only_original_question_no_system_or_think_override(self):
        args = runner.parser().parse_args(["--benchmark", "unused.json"])
        payload = runner.generation_payload(args, "Pergunta original?", "raw_baseline")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Pergunta original?"}])
        self.assertNotIn("think", payload)
        self.assertEqual(payload["options"], {"temperature": 1})

    def test_think_option_is_equal_and_explicit_in_all_modes(self):
        args = runner.parser().parse_args(["--benchmark", "unused.json", "--think", "off"])
        self.assertIs(runner.generation_payload(args, "q", "raw_baseline")["think"], False)
        self.assertIs(runner.generation_payload(args, "q", "words", [])["think"], False)

    def test_rag_prompt_uses_retrieved_context_not_answer_key(self):
        args = runner.parser().parse_args(["--benchmark", "unused.json"])
        hits = [{"payload": {"chunk_id": "source-1", "title": "Tese", "text": "evidência real"}}]
        payload = runner.generation_payload(args, "Pergunta?", "semantic", hits)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("[source-1] Tese", payload["messages"][1]["content"])
        self.assertIn("Pergunta?", payload["messages"][1]["content"])
        self.assertNotIn("GABARITO", json.dumps(payload))
        self.assertNotIn("policy", json.dumps(payload))

    def test_explicit_inference_options(self):
        args = runner.parser().parse_args(["--benchmark", "unused.json", "--seed", "7", "--max-tokens", "400"])
        options = runner.generation_payload(args, "q", "raw_baseline")["options"]
        self.assertEqual(options["seed"], 7)
        self.assertEqual(options["num_predict"], 400)

    def test_corpus_is_not_supported(self):
        with self.assertRaises(SystemExit):
            runner.parser().parse_args(["--benchmark", "unused.json", "--corpus", "data.jsonl"])

    def test_all_modes_run_on_same_question_and_keep_reference_out_of_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark = root / "rag.json"
            benchmark.write_text(json.dumps(dict(benchmark_id="test", policy="POLITICA_NAO_ENVIAR", cases=[
                dict(id="R01", question="q1", reference_answer="GABARITO1"),
                dict(id="R02", question="q2", reference_answer="GABARITO2")
            ])), encoding="utf-8")
            requests, retrieval_calls = [], []
            def fake(base, route, payload=None, timeout=600):
                if route == "/api/tags":
                    return {"models": [{"name": "qwen3.5:2b", "digest": "test"}]}
                requests.append(payload)
                self.assertIn(len(payload["messages"]), (1, 2))
                self.assertNotIn("GABARITO", json.dumps(payload))
                self.assertNotIn("POLITICA", json.dumps(payload))
                return {"message": {"content": "respondido", "thinking": "raciocínio"}, "done_reason": "stop"}
            def fake_search(qdrant, ollama, collection, text, mode, limit):
                retrieval_calls.append(mode)
                return ({"source": {"sha256": "snapshot"}}, [{"id": mode, "score": 0.9, "payload": {
                    "chunk_id": mode + "-chunk", "title": "Título", "text": "evidência"}}])
            out = root / "out"
            with patch.object(runner, "request_json", side_effect=fake), patch.object(runner.hybrid_search, "search_points", side_effect=fake_search):
                self.assertEqual(runner.main(["--benchmark", str(benchmark), "--output", str(out), "--mode", "all", "--collection", "test", "--think", "off"]), 0)
            self.assertEqual([r["messages"][0]["content"] for r in requests[:1]], ["q1"])
            self.assertEqual(retrieval_calls, ["words", "semantic", "hybrid", "words", "semantic", "hybrid"])
            self.assertTrue(all(request["think"] is False for request in requests))
            self.assertIn("GABARITO1", (out / "report.md").read_text())
            self.assertEqual(json.loads((out / "manifest.json").read_text())["collection_snapshot"]["sha256"], "snapshot")
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["raw_baseline"]["answered"], 2)
            self.assertEqual(summary["words"]["answered"], 2)
            self.assertEqual(summary["semantic"]["answered"], 2)
            self.assertEqual(summary["hybrid"]["answered"], 2)

    def test_rag_mode_requires_collection(self):
        with self.assertRaises(SystemExit):
            runner.main(["--benchmark", "missing.json", "--mode", "semantic"])

    def test_failure_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            summary = runner.render_report(p, dict(model="m", benchmark_id="test", case_ids=["R01"], modes=["raw_baseline"]),
                                          [dict(id="R01", mode="raw_baseline", question="q", expected="e", error="timeout")])
            self.assertEqual(summary["raw_baseline"]["failed"], 1)
            self.assertEqual(summary["raw_baseline"]["answered"], 0)


if __name__ == "__main__":
    unittest.main()
