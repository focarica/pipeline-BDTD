from __future__ import annotations

import argparse
import os
import sys

from raw.collector import PilotCollector
from raw.http import BdtdClient
from raw.storage import LocalStorage
from staging.build import StagingReport, build_staging


def _describe_staging_problems(report: StagingReport) -> str:
    parts = [
        f"{len(report.missing_files)} arquivos ausentes",
        f"{len(report.content_type_mismatches)} content-types divergentes",
        f"{len(report.checksum_mismatches)} checksums divergentes",
        f"{len(report.duplicate_ids)} bdtd_id duplicados",
    ]
    return "staging com problemas de integridade: " + ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline da BDTD.")
    
    parser.add_argument("--limit", type=int, default=5, help="documentos a baixar (até 50)")
    parser.add_argument("--max-pages", type=int, default=10, help="máximo de páginas (10)")
    parser.add_argument("--output", default="data/raw", help="diretório local da camada bruta")

    subparsers = parser.add_subparsers(dest="command")
    processed = subparsers.add_parser("processed", help="processa a camada processada")
    processed.add_argument("--raw-dir", default="data/raw", help="diretório da camada bruta")
    processed.add_argument("--output", default="data/processed", help="diretório da camada processada")
    processed.add_argument("--target-tokens", type=int, default=1024, help="tokens por chunk (1024)")
    processed.add_argument("--overlap", type=int, default=128, help="tokens de sobreposição (128)")
    processed.add_argument("--min-len", type=int, default=500, help="tamanho mínimo do texto (500)")
    args = parser.parse_args(argv)

    if args.command == "processed":
        return _run_processed(args)

    try:
        client = BdtdClient()
        collector = PilotCollector(
            client,
            LocalStorage(args.output),
            target_records=args.limit,
            max_pages=args.max_pages,
        )
        _, report = collector.collect()
        staging_report = build_staging(args.output, args.staging)

    except (ValueError, OSError, RuntimeError) as exc:
        print(f"a coleta falhou: {exc}", file=sys.stderr)
        return 1

    print(
        f"coletados {report.record_count} registros: "
        f"{report.downloaded_count} baixados, {report.skipped_count} ignorados"
    )
    
    if not report.valid:
        for issue in report.issues:
            print(f"validação: {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    
    print(f"manifesto: {args.output}/manifests/collection.json")
    print(f"staging: {args.staging}/staging.json")
    if not staging_report.ok:
        print(_describe_staging_problems(staging_report), file=sys.stderr)
        return 1
    return 0


def _run_processed(args: argparse.Namespace) -> int:
    from processed.runner import ProcessedRunner

    runner = ProcessedRunner(
        raw_root=args.raw_dir,
        out_root=args.output,
        target_tokens=args.target_tokens,
        overlap=args.overlap,
        min_len=args.min_len,
    )
    try:
        _, report = runner.run()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"o processamento falhou: {exc}", file=sys.stderr)
        return 1

    print(
        f"processados {report.total} registros: {report.completed} completos, "
        f"{report.no_text} sem texto, {report.filtered} filtrados, "
        f"{report.duplicate} duplicados, {report.skipped} ignorados"
    )
    print(f"manifesto: {args.output}/manifests/processed.json")

    if not report.valid:
        for issue in report.issues:
            print(f"validação: {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
