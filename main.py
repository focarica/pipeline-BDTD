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
        f"{len(report.missing_records)} registros sem arquivo",
    ]
    return "staging com problemas de integridade: " + ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline da BDTD.")
    
    parser.add_argument("--limit", type=int, default=5, help="registros a coletar (5)")
    parser.add_argument("--max-pages", type=int, default=100, help="máximo de páginas (100)")
    parser.add_argument("--start-page", type=int, default=1, help="página inicial da busca (1)")
    parser.add_argument("--output", default="data/raw", help="diretório local da camada bruta")
    parser.add_argument("--staging", default="data/staging", help="diretório local da camada staging")
    parser.add_argument(
        "--only-staging",
        action="store_true",
        help="pula a coleta e monta o staging a partir do raw existente",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="remove do raw os registros e arquivos fora do manifesto atual",
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
    sync.add_argument("--workers", type=int, default=8, help="uploads em paralelo (8)")
    sync.add_argument("--dry-run", action="store_true", help="lista o que seria enviado sem enviar")

    drive_sync = subparsers.add_parser("drive-sync", help="sincroniza camadas locais com Shared Drive (deduplicacao por sha256)")
    drive_sync.add_argument(
        "--layer",
        action="append",
        choices=["raw", "staging", "processed", "curated"],
        help="camada a sincronizar (pode repetir); padrão: raw",
    )
    drive_sync.add_argument("--folder-id", default=None, help="ID da pasta no Drive (padrão: GDRIVE_FOLDER_ID)")
    drive_sync.add_argument("--shared-drive-id", default=None, help="ID do Shared Drive (opcional)")
    drive_sync.add_argument("--credentials", default=None, help="caminho do JSON da SA (padrão: GOOGLE_APPLICATION_CREDENTIALS)")
    drive_sync.add_argument("--raw-dir", default="data/raw", help="diretório da camada bruta")
    drive_sync.add_argument("--staging-dir", default="data/staging", help="diretório da camada staging")
    drive_sync.add_argument("--processed-dir", default="data/processed", help="diretório da camada processada")
    drive_sync.add_argument("--curated-dir", default="data/curated", help="diretório da camada curated")
    drive_sync.add_argument("--workers", type=int, default=4, help="uploads em paralelo (4, limite Drive)")
    drive_sync.add_argument("--dry-run", action="store_true", help="lista o que seria enviado sem enviar")

    migrate = subparsers.add_parser("migrate-r2-to-drive", help="migra camadas do R2 para o Drive (com dedup)")
    migrate.add_argument("--folder-id", default=None, help="ID da pasta no Drive (padrão: GDRIVE_FOLDER_ID)")
    migrate.add_argument("--shared-drive-id", default=None, help="ID do Shared Drive")
    migrate.add_argument("--bucket", default=None, help="bucket R2 (padrão: R2_BUCKET)")
    migrate.add_argument("--prefix", default="raw", help="prefixo no R2 a migrar (padrão: raw)")
    migrate.add_argument("--workers", type=int, default=4, help="downloads/uploads paralelos (4)")
    migrate.add_argument("--dry-run", action="store_true", help="lista o que seria migrado sem enviar")
    migrate.add_argument("--tmp-dir", default=None, help="diretório temporário para staging (padrão: temp do sistema)")

    csv_collect = subparsers.add_parser(
        "csv", help="coleta um piloto limitado usando exportação CSV da BDTD"
    )
    csv_collect.add_argument("--input", required=True, help="caminho do CSV exportado da BDTD")
    csv_collect.add_argument("--limit", type=int, default=50, help="downloads novos desejados (50)")
    csv_collect.add_argument(
        "--max-candidates",
        type=int,
        default=1000,
        help="máximo de candidatos elegíveis examinados (1000)",
    )
    csv_collect.add_argument("--output", default="data/raw", help="diretório local da camada bruta")

    run_all = subparsers.add_parser("all", help="roda a esteira completa: coleta, staging, processed e curated")
    run_all.add_argument("--limit", type=int, default=5, help="registros a coletar (5)")
    run_all.add_argument("--max-pages", type=int, default=100, help="máximo de páginas (100)")
    run_all.add_argument("--start-page", type=int, default=1, help="página inicial da busca (1)")
    run_all.add_argument("--output", default="data/raw", help="diretório local da camada bruta")
    run_all.add_argument("--staging", default="data/staging", help="diretório local da camada staging")
    run_all.add_argument("--processed-dir", default="data/processed", help="diretório da camada processada")
    run_all.add_argument("--curated-dir", default="data/curated", help="diretório da camada curated")
    run_all.add_argument("--target-tokens", type=int, default=1024, help="tokens por chunk (1024)")
    run_all.add_argument("--overlap", type=int, default=128, help="tokens de sobreposição (128)")
    run_all.add_argument("--min-len", type=int, default=500, help="tamanho mínimo do texto (500)")
    run_all.add_argument("--prune", action="store_true", help="remove do raw os registros e arquivos fora do manifesto atual")
    args = parser.parse_args(argv)

    if args.command == "processed":
        return _run_processed(args)

    if args.command == "curated":
        return _run_curated(args)

    if args.command == "sync":
        return _run_sync(args)

    if args.command == "drive-sync":
        return _run_drive_sync(args)

    if args.command == "migrate-r2-to-drive":
        return _run_migrate_r2_to_drive(args)

    if args.command == "csv":
        return _run_csv(args)

    if args.command == "all":
        return _run_all(args)

    if args.only_staging:
        try:
            staging_report = build_staging(args.output, args.staging, prune=args.prune)
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
            start_page=args.start_page,
        )
        _, report = collector.collect()
        staging_report = build_staging(args.output, args.staging, prune=args.prune)

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


def _run_csv(args: argparse.Namespace) -> int:
    from raw.csv_collector import CsvPilotCollector

    try:
        collector = CsvPilotCollector(
            BdtdClient(),
            LocalStorage(args.output),
            target_records=args.limit,
        )
        manifest, report = collector.collect_csv(
            args.input,
            max_candidates=args.max_candidates,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"a coleta CSV falhou: {exc}", file=sys.stderr)
        return 1

    summary = manifest.get("run_summary", {})
    print(
        f"piloto CSV: {report.downloaded_count}/{args.limit} downloads; "
        f"{report.skipped_count} ignorados; "
        f"{summary.get('eligible_candidates_scanned', 0)} candidatos examinados"
    )
    print(f"manifesto: {args.output}/manifests/collection.json")
    for warning in manifest.get("warnings", []):
        print(f"aviso: {warning}", file=sys.stderr)
    if not report.valid:
        for issue in report.issues:
            print(f"validação: {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    return 0 if summary.get("target_reached") else 1


def _run_all(args: argparse.Namespace) -> int:
    from processed.runner import ProcessedRunner

    from curated.build import build_curated

    try:
        client = BdtdClient()
        collector = PilotCollector(
            client,
            LocalStorage(args.output),
            target_records=args.limit,
            max_pages=args.max_pages,
            start_page=args.start_page,
        )
        collection_manifest, collect_report = collector.collect()
        staging_report = build_staging(args.output, args.staging, prune=args.prune)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"a coleta falhou: {exc}", file=sys.stderr)
        return 1

    print(
        f"coletados {collect_report.record_count} registros: "
        f"{collect_report.downloaded_count} baixados, {collect_report.skipped_count} ignorados"
    )
    if not collect_report.valid:
        for issue in collect_report.issues:
            print(f"validação: {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    if not staging_report.ok:
        print(_describe_staging_problems(staging_report), file=sys.stderr)
        return 1

    runner = ProcessedRunner(
        raw_root=args.output,
        out_root=args.processed_dir,
        target_tokens=args.target_tokens,
        overlap=args.overlap,
        min_len=args.min_len,
    )
    try:
        _, processed_report = runner.run()
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"o processamento falhou: {exc}", file=sys.stderr)
        return 1
    print(
        f"processados {processed_report.total} registros: {processed_report.completed} completos, "
        f"{processed_report.no_text} sem texto, {processed_report.filtered} filtrados, "
        f"{processed_report.duplicate} duplicados, {processed_report.skipped} ignorados"
    )
    if not processed_report.valid:
        for issue in processed_report.issues:
            print(f"validação: {issue.code}: {issue.message}", file=sys.stderr)
        return 1

    try:
        curated_report = build_curated(args.processed_dir, args.curated_dir)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"o curated falhou: {exc}", file=sys.stderr)
        return 1
    print(f"curated: {curated_report.document_count} documentos, {curated_report.chunk_count} chunks")
    if not curated_report.ok:
        print(
            f"curated com documentos sem chunks: {len(curated_report.missing_chunks)}",
            file=sys.stderr,
        )
        return 1

    run_summary = collection_manifest.get("run_summary", {})
    if not run_summary.get("target_reached", False):
        print(
            "esteira parcial: a coleta não atingiu o alvo de "
            f"{run_summary.get('requested_download_count', args.limit)} downloads; "
            "veja os avisos de paginação e tente novamente com --start-page 1",
            file=sys.stderr,
        )
        return 1

    print("esteira completa concluída")
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
            report = sync_directory(
                client,
                layer_dirs[layer],
                bucket,
                layer,
                max_workers=args.workers,
                dry_run=args.dry_run,
            )
        except RuntimeError as exc:
            print(f"o sync de {layer} falhou: {exc}", file=sys.stderr)
            ok = False
            continue
        print(
            f"{layer}: {len(report.uploaded)} enviados, {len(report.skipped)} já "
            f"atualizados, {len(report.failed)} falharam, {len(report.pending)} pendentes"
        )
        ok = ok and report.ok

    return 0 if ok else 1


def _run_drive_sync(args: argparse.Namespace) -> int:
    import dotenv

    from remote.drive import DriveConfigError, build_drive_client, sync_directory as drive_sync_directory

    dotenv.load_dotenv()
    folder_id = args.folder_id or os.environ.get("GDRIVE_FOLDER_ID", "").strip() or "1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8"
    shared_drive_id = args.shared_drive_id or os.environ.get("GDRIVE_SHARED_DRIVE_ID", "").strip() or None
    if args.credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.credentials
    if not folder_id:
        print("informe --folder-id ou defina GDRIVE_FOLDER_ID", file=sys.stderr)
        return 1

    layers = args.layer or ["raw"]
    layer_dirs = {
        "raw": args.raw_dir,
        "staging": args.staging_dir,
        "processed": args.processed_dir,
        "curated": args.curated_dir,
    }

    try:
        service = build_drive_client()
    except DriveConfigError as exc:
        print(f"o drive-sync falhou: {exc}", file=sys.stderr)
        return 1

    ok = True
    for layer in layers:
        local_dir = layer_dirs[layer]
        try:
            report = drive_sync_directory(
                service,
                local_dir,
                folder_id,
                layer,
                max_workers=args.workers,
                dry_run=args.dry_run,
                shared_drive_id=shared_drive_id,
            )
        except RuntimeError as exc:
            print(f"o drive-sync de {layer} falhou: {exc}", file=sys.stderr)
            ok = False
            continue
        print(
            f"{layer}: {len(report.uploaded)} enviados, {len(report.skipped)} ja atualizados, "
            f"{len(report.duplicate)} duplicados (sha256), {len(report.failed)} falharam, {len(report.pending)} pendentes"
        )
        if report.duplicate:
            for rel, remote_path in report.duplicate_of:
                print(f"  duplicado: {rel} ja existe como {remote_path}", file=sys.stderr)
        ok = ok and report.ok

    return 0 if ok else 1


def _run_migrate_r2_to_drive(args: argparse.Namespace) -> int:
    import dotenv

    from remote.migrate import migrate_r2_to_drive

    dotenv.load_dotenv()
    folder_id = args.folder_id or os.environ.get("GDRIVE_FOLDER_ID", "").strip() or "1UImdu0YmqoPd8ulwHfDUIMaHBAuIq_N8"
    shared_drive_id = args.shared_drive_id or os.environ.get("GDRIVE_SHARED_DRIVE_ID", "").strip() or None
    bucket = args.bucket or os.environ.get("R2_BUCKET", "").strip()
    if not folder_id:
        print("informe --folder-id ou GDRIVE_FOLDER_ID", file=sys.stderr)
        return 1
    if not bucket:
        print("informe --bucket ou R2_BUCKET", file=sys.stderr)
        return 1
    try:
        report = migrate_r2_to_drive(
            bucket=bucket,
            prefix=args.prefix,
            folder_id=folder_id,
            shared_drive_id=shared_drive_id,
            max_workers=args.workers,
            dry_run=args.dry_run,
            tmp_dir=args.tmp_dir,
        )
    except RuntimeError as exc:
        print(f"a migracao falhou: {exc}", file=sys.stderr)
        return 1
    print(
        f"migracao {args.prefix}: {len(report.uploaded)} enviados ao Drive, "
        f"{len(report.skipped)} ja existentes, {len(report.duplicate)} duplicados, "
        f"{len(report.failed)} falharam"
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
