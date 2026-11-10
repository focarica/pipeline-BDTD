# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Testa o modelo no Ollama com perguntas isoladas, sem sistema, corpus ou RAG."""

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.error
import urllib.request


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def request_json(base, route, payload=None, timeout=600):
    req = urllib.request.Request(
        base.rstrip("/") + route,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Falha ao consultar Ollama em {base}: {exc}") from exc


def generation_payload(args, question):
    # Uma única mensagem. Não usa policy, reference_answer ou outras questões.
    payload = {"model": args.model, "stream": False,
               "messages": [{"role": "user", "content": question}]}
    options = {}
    for flag, key in [("temperature", "temperature"), ("seed", "seed"),
                      ("num_ctx", "num_ctx"), ("max_tokens", "num_predict")]:
        value = getattr(args, flag)
        if value is not None:
            options[key] = value
    if options:
        payload["options"] = options
    # Não força think=false: preserva o comportamento do modelo no Ollama.
    return payload


def chat(args, payload):
    start = time.perf_counter()
    response = request_json(args.url, "/api/chat", payload, args.timeout)
    message = response.get("message", {})
    answer = message.get("content", "").strip()
    if not answer:
        raise RuntimeError("Ollama retornou resposta final vazia; confira limite de tokens e configuração do modelo")
    return answer, message.get("thinking", ""), {
        "wall_seconds": time.perf_counter() - start,
        **{k: response.get(k) for k in ("prompt_eval_count", "eval_count", "done_reason",
                                       "total_duration", "load_duration", "eval_duration")},
    }


def render_report(directory, manifest, records, interrupted=False):
    answered = [r for r in records if "answer" in r]
    summary = {
        "mode": "raw_baseline", "selected": len(manifest["case_ids"]),
        "attempted": len(records), "answered": len(answered),
        "failed": sum("error" in r for r in records),
        "not_completed": len(manifest["case_ids"]) - len(records),
        "interrupted": interrupted,
        "truncated": sum(r["timing"].get("done_reason") == "length" for r in answered),
        "median_seconds": statistics.median(r["timing"]["wall_seconds"] for r in answered) if answered else None,
        "quality_score": None, "evaluation": "Comparação esperado × respondido; revisão humana pendente.",
    }
    lines = ["# Modelo sem RAG — esperado × respondido", "",
             f"Modelo: `{manifest['model']}` | benchmark: `{manifest['benchmark_id']}`", "",
             "Cada chamada contém somente a pergunta original. Sem mensagem de sistema adicionada pelo runner, corpus, recuperação ou juiz.", "",
             "Os resultados anteriores com política científica não são este baseline e não devem ser misturados.", "",
             "## Resumo", "", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```", ""]
    for r in records:
        lines += [f"## {r['id']}", "", "### Pergunta", "", r["question"], "",
                  "### Esperado", "", r["expected"], "", "### Respondido", "",
                  r.get("answer", "ERRO: " + r.get("error", "")), ""]
        if r.get("timing"):
            lines += [f"Tempo: {r['timing']['wall_seconds']:.1f}s. Truncado: {r['timing'].get('done_reason') == 'length'}.", ""]
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmark", type=Path, required=True, help="JSON com perguntas e gabaritos")
    p.add_argument("--model", default="qwen3.5:2b")
    p.add_argument("--url", default="http://127.0.0.1:11434")
    p.add_argument("--output", type=Path, help="diretório novo; padrão results/<horário>")
    p.add_argument("--limit", type=int, help="primeiras N perguntas")
    p.add_argument("--case", action="append", default=[], help="ID específico; repetível")
    # Preserva temperature=1, já configurada no arquivo antes desta simplificação.
    p.add_argument("--temperature", type=float, default=1)
    p.add_argument("--seed", type=int, help="opcional; sem fixação por padrão")
    p.add_argument("--num-ctx", type=int, help="opcional; usa configuração do Ollama se omitido")
    p.add_argument("--max-tokens", type=int, help="opcional; usa configuração do Ollama se omitido")
    p.add_argument("--timeout", type=float, default=600)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    for name in ("limit", "num_ctx", "max_tokens", "timeout"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            p.error(f"{name} deve ser positivo")
    if args.temperature < 0:
        p.error("temperature não pode ser negativa")
    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    cases = benchmark["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark sem casos")
    for c in cases:
        for field in ("id", "question", "reference_answer"):
            if not isinstance(c.get(field), str) or not c[field].strip():
                raise ValueError(f"Caso sem campo válido: {field}")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("IDs duplicados no benchmark")
    if args.case:
        missing = set(args.case) - {c["id"] for c in cases}
        if missing:
            p.error(f"IDs inexistentes: {sorted(missing)}")
        cases = [c for c in cases if c["id"] in args.case]
    if args.limit:
        cases = cases[:args.limit]
    tags = request_json(args.url, "/api/tags", timeout=10).get("models", [])
    available = {m["name"]: m for m in tags}
    if args.model not in available:
        raise ValueError(f"Modelo {args.model!r} não está no Ollama. Disponíveis: {', '.join(available)}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output or Path(__file__).resolve().parent / "results" / stamp
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(), "mode": "raw_baseline",
        "benchmark_id": benchmark.get("benchmark_id", args.benchmark.stem),
        "benchmark_sha256": sha(args.benchmark), "benchmark_path": str(args.benchmark.resolve()),
        "runner_sha256": sha(Path(__file__)), "model": args.model,
        "model_metadata": available[args.model], "case_ids": [c["id"] for c in cases],
        "options": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "system_message": None, "retrieval": None, "judge": None,
        "note": "O runner não adiciona sistema; template, configuração e alinhamento próprios do modelo/Ollama continuam ativos.",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records, interrupted = [], False
    try:
        with (output / "answers.jsonl").open("a", encoding="utf-8") as stream:
            for case in cases:
                print(f"\n{'=' * 65}\n{case['id']} [modelo sem contexto adicional]\nPERGUNTA: {case['question']}\nESPERADO: {case['reference_answer']}", flush=True)
                r = {"id": case["id"], "mode": "raw_baseline", "question": case["question"],
                     "expected": case["reference_answer"], "request": generation_payload(args, case["question"])}
                try:
                    r["answer"], r["thinking"], r["timing"] = chat(args, r["request"])
                    print(f"RESPONDIDO: {r['answer']}\nTempo: {r['timing']['wall_seconds']:.1f}s", flush=True)
                    if r["timing"].get("done_reason") == "length":
                        print("AVISO: limite de geração atingido; resposta pode estar incompleta.", flush=True)
                except RuntimeError as exc:
                    r["error"] = str(exc)
                    print(f"ERRO: {exc}", flush=True)
                records.append(r)
                stream.write(json.dumps(r, ensure_ascii=False) + "\n")
                stream.flush()
                render_report(output, manifest, records)
    except KeyboardInterrupt:
        interrupted = True
        print("\nInterrompido; resultados concluídos foram preservados.", flush=True)
    finally:
        summary = render_report(output, manifest, records, interrupted)
    print("\nRESUMO\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nComparação esperado × respondido: {output.resolve() / 'report.md'}")
    return 130 if interrupted else int(any("error" in r for r in records))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)
