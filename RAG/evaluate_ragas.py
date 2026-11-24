# /// script
# requires-python = ">=3.11"
# dependencies = ["ragas>=0.4.4,<0.5", "openai>=1"]
# ///
"""Pontua fidelidade ao contexto e cria uma planilha simples para revisão humana."""

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path

QUESTION_MARKER = "\n\nPERGUNTA:\n"
CONTEXT_MARKER = "TRECHOS RECUPERADOS:\n"


def cases(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("mode") != "semantic" or row.get("question_format") != "open":
                continue
            request = row.get("request", {})
            messages = request.get("messages", [])
            if "answer" not in row or len(messages) < 2:
                continue
            prompt = messages[-1].get("content", "")
            if CONTEXT_MARKER not in prompt or QUESTION_MARKER not in prompt:
                continue
            context = prompt.split(CONTEXT_MARKER, 1)[1].split(QUESTION_MARKER, 1)[0].strip()
            if context and context != "Nenhum trecho recuperado.":
                yield row, context


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, required=True, help="answers.jsonl de uma execução")
    parser.add_argument("--output", type=Path, help="CSV para juiz e revisão humana")
    parser.add_argument("--model", default=os.getenv("RAGAS_MODEL", "gpt-4o-mini"))
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL"))
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("configure OPENAI_API_KEY (ou a variável aceita pelo provedor OpenAI-compatible)")

    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import Faithfulness

    client_args = {"api_key": os.environ["OPENAI_API_KEY"]}
    if args.base_url:
        client_args["base_url"] = args.base_url
    llm = llm_factory(args.model, client=AsyncOpenAI(**client_args))
    metric = Faithfulness(llm=llm)
    output = args.output or args.answers.with_name("ragas_human_review.csv")
    results = []

    for row, context in cases(args.answers):
        result = {
            "id": row["id"],
            "question": row["question"],
            "answer": row["answer"],
            "faithfulness": "",
            "judge_error": "",
            "human_score_0_1": "",
            "human_notes": "",
        }
        try:
            score = await metric.ascore(
                user_input=row["question"],
                response=row["answer"],
                retrieved_contexts=[context],
            )
            result["faithfulness"] = score.value
        except Exception as exc:
            result["judge_error"] = str(exc)
        results.append(result)
        print(f"{row['id']}: {result['faithfulness'] or 'ERRO ' + result['judge_error']}", flush=True)

    if not results:
        parser.error("answers.jsonl não contém respostas abertas do braço semantic com contexto")
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"Juiz RAGAS + revisão humana: {output.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
