"""Validação estrutural do benchmark de RAG, sem modelos ou acesso à rede."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    rag = json.loads((ROOT / "rag.json").read_text(encoding="utf-8"))
    source = json.loads((ROOT / "evidence.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in rag["cases"]] == [f"R{n:02d}" for n in range(1, 31)]
    refs = set(source["evidence"]) | {f"{alias}.abstract" for alias in source["documents"]}
    for case in rag["cases"]:
        assert case["question"] and case["reference_answer"], case["id"]
        assert case["required_claims"] and case["critical_errors"], case["id"]
        assert case["evidence_groups"], case["id"]
        for group in case["evidence_groups"]:
            assert group and all(ref in refs for ref in group), case["id"]
            for ref in group:
                if ref.endswith(".abstract"):
                    assert source["documents"][ref.split(".")[0]]["abstract"], ref
                else:
                    assert source["evidence"][ref]["text"], ref
    print("OK: 30 casos de RAG; todas as evidências resolvidas. Gabaritos não avaliados semanticamente.")


if __name__ == "__main__":
    main()
