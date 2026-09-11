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
    
    parser.add_argument("--limit", type=int, default=5, help="registros a coletar (5)")
    parser.add_argument("--max-pages", type=int, default=10, help="máximo de páginas (10)")
    parser.add_argument("--output", default="data/raw", help="diretório local da camada bruta")
    parser.add_argument("--staging", default="data/staging", help="diretório local da camada staging")
    parser.add_argument(
        "--only-staging",
        action="store_true",
        help="pula a coleta e monta o staging a partir do raw existente",
    )
    args = parser.parse_args(argv)

    if args.only_staging:
        try:
            staging_report = build_staging(args.output, args.staging)
        except (ValueError, OSError, RuntimeError) as exc:
            print(f"o staging falhou: {exc}", file=sys.stderr)
            return 1
        print(f"staging: {args.staging}/staging.json")
        if not staging_report.ok:
            print(_describe_staging_problems(staging_report), file=sys.stderr)
            return 1
        return 0

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


if __name__ == "__main__":
    raise SystemExit(main())
