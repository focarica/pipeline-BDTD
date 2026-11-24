"""Validação estrutural do benchmark de RAG, sem modelos ou acesso à rede."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    rag = json.loads((ROOT / "rag.json").read_text(encoding="utf-8"))
    source = json.loads((ROOT / "evidence.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in rag["cases"]] == [f"R{n:02d}" for n in range(1, 31)]
    mcq = [c for c in rag["cases"] if "choices" in c]
    assert len(mcq) == 10, f"esperadas 10 questões de múltipla escolha, encontradas {len(mcq)}"
    refs = set(source["evidence"]) | {f"{alias}.abstract" for alias in source["documents"]}
    for case in rag["cases"]:
        assert case["question"] and case["reference_answer"], case["id"]
        assert case["required_claims"] and case["critical_errors"], case["id"]
        assert case["evidence_groups"], case["id"]
        if "choices" in case:
            assert list(case["choices"]) == ["A", "B", "C", "D"], case["id"]
            assert case["correct_option"] in case["choices"], case["id"]
            assert len(set(case["choices"].values())) == 4, case["id"]
        for group in case["evidence_groups"]:
            assert group and all(ref in refs for ref in group), case["id"]
            for ref in group:
                if ref.endswith(".abstract"):
                    assert source["documents"][ref.split(".")[0]]["abstract"], ref
                else:
                    assert source["evidence"][ref]["text"], ref
    print(f"OK: 30 casos ({len(mcq)} múltipla escolha, {len(rag['cases']) - len(mcq)} abertas); alternativas e referências resolvidas.")


if __name__ == "__main__":
    main()
