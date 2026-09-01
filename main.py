from __future__ import annotations

import argparse
import os
import sys

from raw.collector import PilotCollector
from raw.http import BdtdClient
from raw.storage import LocalStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline da BDTD.")
    
    parser.add_argument("--limit", type=int, default=5, help="registros a coletar (5)")
    parser.add_argument("--max-pages", type=int, default=10, help="máximo de páginas (10)")
    parser.add_argument("--output", default="data/raw", help="diretório local da camada bruta")
    args = parser.parse_args(argv)

    try:
        client = BdtdClient()
        collector = PilotCollector(
            client,
            LocalStorage(args.output),
            target_records=args.limit,
            max_pages=args.max_pages,
        )
        _, report = collector.collect()
        
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
