import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "evaluate_ragas", Path(__file__).resolve().parents[1] / "evaluate_ragas.py"
)
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


class RagasInputTests(unittest.TestCase):
    def test_only_open_semantic_answers_and_exact_prompt_context(self):
        rows = [
            {
                "id": "R01",
                "mode": "semantic",
                "question_format": "open",
                "question": "O que foi observado?",
                "answer": "Houve melhora.",
                "request": {
                    "messages": [
                        {"role": "system", "content": "instrução"},
                        {
                            "role": "user",
                            "content": "TRECHOS RECUPERADOS:\ntexto que foi enviado\n\nPERGUNTA:\nO que foi observado?",
                        },
                    ]
                },
            },
            {"id": "R02", "mode": "raw_baseline", "question_format": "open"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            selected = list(evaluator.cases(path))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0]["id"], "R01")
        self.assertEqual(selected[0][1], "texto que foi enviado")


if __name__ == "__main__":
    unittest.main()
