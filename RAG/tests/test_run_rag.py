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
        payload = runner.generation_payload(args, "Pergunta original?")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Pergunta original?"}])
        self.assertNotIn("think", payload)
        self.assertEqual(payload["options"], {"temperature": 1})

    def test_explicit_inference_options(self):
        args = runner.parser().parse_args(["--benchmark", "unused.json", "--seed", "7", "--max-tokens", "400"])
        options = runner.generation_payload(args, "q")["options"]
        self.assertEqual(options["seed"], 7)
        self.assertEqual(options["num_predict"], 400)

    def test_corpus_is_not_supported(self):
        with self.assertRaises(SystemExit):
            runner.parser().parse_args(["--benchmark", "unused.json", "--corpus", "data.jsonl"])

    def test_end_to_end_questions_isolated_and_reference_never_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmark = root / "rag.json"
            benchmark.write_text(json.dumps(dict(benchmark_id="test", policy="POLITICA_NAO_ENVIAR", cases=[
                dict(id="R01", question="q1", reference_answer="GABARITO1"),
                dict(id="R02", question="q2", reference_answer="GABARITO2")
            ])), encoding="utf-8")
            requests = []
            def fake(base, route, payload=None, timeout=600):
                if route == "/api/tags":
                    return {"models": [{"name": "qwen3.5:2b", "digest": "test"}]}
                requests.append(payload)
                self.assertEqual(len(payload["messages"]), 1)
                self.assertNotIn("GABARITO", json.dumps(payload))
                self.assertNotIn("POLITICA", json.dumps(payload))
                return {"message": {"content": "respondido", "thinking": "raciocínio"}, "done_reason": "stop"}
            out = root / "out"
            with patch.object(runner, "request_json", side_effect=fake):
                self.assertEqual(runner.main(["--benchmark", str(benchmark), "--output", str(out)]), 0)
            self.assertEqual([r["messages"][0]["content"] for r in requests], ["q1", "q2"])
            self.assertIn("GABARITO1", (out / "report.md").read_text())
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["answered"], 2)
            self.assertIsNone(summary["quality_score"])

    def test_failure_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            summary = runner.render_report(p, dict(model="m", benchmark_id="test", case_ids=["R01"]),
                                          [dict(id="R01", question="q", expected="e", error="timeout")])
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["answered"], 0)


if __name__ == "__main__":
    unittest.main()
