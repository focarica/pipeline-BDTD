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

    subparsers = parser.add_subparsers(dest="command")
    processed = subparsers.add_parser("processed", help="processa a camada processada")
    processed.add_argument("--raw-dir", default="data/raw", help="diretório da camada bruta")
    processed.add_argument("--output", default="data/processed", help="diretório da camada processada")
    processed.add_argument("--target-tokens", type=int, default=1024, help="tokens por chunk (1024)")
    processed.add_argument("--overlap", type=int, default=128, help="tokens de sobreposição (128)")
    processed.add_argument("--min-len", type=int, default=500, help="tamanho mínimo do texto (500)")

    curated = subparsers.add_parser("curated", help="gera a camada curated a partir do processed")
    curated.add_argument("--processed-dir", default="data/processed", help="diretório da camada processada")
    curated.add_argument("--output", default="data/curated", help="diretório da camada curated")

    sync = subparsers.add_parser("sync", help="sincroniza camadas locais com um bucket R2 da Cloudflare")
    sync.add_argument(
        "--layer",
        action="append",
        choices=["raw", "staging", "processed", "curated"],
        help="camada a sincronizar (pode repetir); padrão: raw e curated",
    )
    sync.add_argument("--bucket", default=None, help="bucket R2 (padrão: variável de ambiente R2_BUCKET)")
    sync.add_argument("--raw-dir", default="data/raw", help="diretório da camada bruta")
    sync.add_argument("--staging-dir", default="data/staging", help="diretório da camada staging")
    sync.add_argument("--processed-dir", default="data/processed", help="diretório da camada processada")
    sync.add_argument("--curated-dir", default="data/curated", help="diretório da camada curated")
    args = parser.parse_args(argv)

    if args.command == "processed":
        return _run_processed(args)

    if args.command == "curated":
        return _run_curated(args)

    if args.command == "sync":
        return _run_sync(args)

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


def _run_curated(args: argparse.Namespace) -> int:
    from curated.build import build_curated

    try:
        report = build_curated(args.processed_dir, args.output)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"o curated falhou: {exc}", file=sys.stderr)
        return 1

    print(f"curated: {report.document_count} documentos, {report.chunk_count} chunks")
    print(f"manifesto: {args.output}/manifests/curated.json")
    print(f"datacard: {args.output}/DATACARD.md")

    if not report.ok:
        print(
            f"curated com documentos sem chunks: {len(report.missing_chunks)}",
            file=sys.stderr,
        )
        return 1
    return 0


def _run_sync(args: argparse.Namespace) -> int:
    import dotenv

    from remote.r2 import R2ConfigError, build_client, sync_directory

    dotenv.load_dotenv()
    bucket = args.bucket or os.environ.get("R2_BUCKET", "")
    if not bucket:
        print("informe --bucket ou defina a variável de ambiente R2_BUCKET", file=sys.stderr)
        return 1

    layers = args.layer or ["raw", "curated"]
    layer_dirs = {
        "raw": args.raw_dir,
        "staging": args.staging_dir,
        "processed": args.processed_dir,
        "curated": args.curated_dir,
    }

    try:
        client = build_client()
    except R2ConfigError as exc:
        print(f"o sync falhou: {exc}", file=sys.stderr)
        return 1

    ok = True
    for layer in layers:
        try:
            report = sync_directory(client, layer_dirs[layer], bucket, layer)
        except RuntimeError as exc:
            print(f"o sync de {layer} falhou: {exc}", file=sys.stderr)
            ok = False
            continue
        print(
            f"{layer}: {len(report.uploaded)} enviados, {len(report.skipped)} já "
            f"atualizados, {len(report.failed)} falharam"
        )
        ok = ok and report.ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())