#!/usr/bin/env python3
"""
SP-API Search Query Performance (SQP) & Search Catalog Performance (SCP) Pull Script

Pulls SQP and SCP data for all active ASINs across NA marketplaces.
Designed to run weekly (Tuesday) for weekly data, and monthly (4th) for monthly data.

Features:
- ASIN batching (18 ASINs per request, 200-char limit)
- Batch-level resume (tracks which batches completed via JSONB)
- Rate-limit-aware (shares createReport budget with daily pulls)
- Per-ASIN error tracking (suppresses consistently failing ASINs after 3 failures)

Usage:
    python pull_sqp.py                                     # Latest week, SQP + SCP
    python pull_sqp.py --report-type SQP                   # SQP only
    python pull_sqp.py --report-type SCP                   # SCP only
    python pull_sqp.py --period-type MONTH                 # Monthly data
    python pull_sqp.py --period-start 2026-01-26 --period-end 2026-02-01
    python pull_sqp.py --marketplace USA                   # Single marketplace
    python pull_sqp.py --resume                            # Resume interrupted pull
    python pull_sqp.py --dry-run                           # Show what would be pulled
    python pull_sqp.py --force                             # Force re-pull even if data exists
"""

import os
import sys
import argparse
import time
import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.auth import get_access_token
from scripts.utils.api_client import SPAPIClient, SPAPIError
from scripts.utils.alerting import alert_failure, alert_partial, send_summary
from scripts.utils.db import (
    MARKETPLACE_UUIDS,
    upsert_sqp_data,
    upsert_scp_data,
    create_sqp_pull_record,
    update_sqp_pull_status,
    get_existing_sqp_pull,
    record_asin_error,
    get_active_asins_for_sqp,
)
from scripts.utils.sqp_reports import (
    batch_asins,
    get_latest_available_week,
    get_latest_available_month,
    pull_sqp_batch,
    pull_scp_batch,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Marketplaces by region for Brand Analytics (SQP/SCP)
# MX excluded (Brand Analytics not available)
MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA"],
    "EU": ["UK", "DE", "FR", "IT", "ES"],
    "FE": ["AU"],
    "UAE": ["UAE"]
}


def pull_for_marketplace(
    client: SPAPIClient,
    marketplace_code: str,
    report_type: str,
    period_start: date,
    period_end: date,
    period_type: str,
    region: str = "NA",
    resume: bool = True,
    force: bool = False,
    dry_run: bool = False
) -> Dict:
    """
    Pull SQP or SCP data for a single marketplace and period.

    Returns:
        Dict with status, counts, and timing info
    """
    result = {
        "marketplace": marketplace_code,
        "report_type": report_type,
        "period": f"{period_start} to {period_end}",
        "status": "pending",
        "total_rows": 0,
        "total_queries": 0,
        "total_batches": 0,
        "completed_batches": 0,
        "failed_batches": 0,
        "error": None
    }

    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]
    start_time = time.time()

    try:
        # Check for existing pull
        existing = get_existing_sqp_pull(marketplace_code, report_type, period_start, period_end, period_type)
        if existing and not force:
            if existing["status"] == "completed":
                print(f"  Skipping {marketplace_code} {report_type} {period_start} (already completed, {existing['total_rows']} rows)")
                result["status"] = "skipped"
                result["total_rows"] = existing.get("total_rows", 0)
                return result
            elif existing["status"] in ("processing", "partial") and resume:
                print(f"  Resuming {marketplace_code} {report_type} {period_start} ({existing['completed_batches']}/{existing['total_batches']} batches)")

        # Get active ASINs
        asins = get_active_asins_for_sqp(marketplace_code)
        if not asins:
            print(f"  No active ASINs found for {marketplace_code}, skipping")
            result["status"] = "skipped"
            return result

        # Batch ASINs
        batches = batch_asins(asins)
        result["total_batches"] = len(batches)

        print(f"  {marketplace_code} {report_type}: {len(asins)} ASINs in {len(batches)} batches ({period_type} {period_start})")

        if dry_run:
            result["status"] = "dry_run"
            return result

        # Create/update pull tracking record
        pull_id = create_sqp_pull_record(
            marketplace_code=marketplace_code,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            period_type=period_type,
            total_batches=len(batches),
            total_asins=len(asins)
        )

        # Get existing batch status for resume (but NOT when forcing re-pull)
        existing_batch_status = {}
        if existing and resume and not force and existing.get("batch_status"):
            existing_batch_status = existing["batch_status"]

        total_rows_upserted = 0
        total_queries = 0
        batch_status = dict(existing_batch_status)

        for batch_idx, batch in enumerate(batches):
            batch_key = str(batch_idx)

            # Skip completed batches on resume
            if batch_status.get(batch_key) == "completed":
                result["completed_batches"] += 1
                continue

            try:
                print(f"    Batch {batch_idx + 1}/{len(batches)} ({len(batch)} ASINs)...", end=" ", flush=True)

                if report_type == "SQP":
                    rows, query_count = pull_sqp_batch(
                        client=client,
                        marketplace_code=marketplace_code,
                        asins=batch,
                        period_start=period_start,
                        period_end=period_end,
                        period_type=period_type,
                        region=region,
                        marketplace_id=marketplace_id
                    )
                    total_queries += query_count
                else:  # SCP
                    rows = pull_scp_batch(
                        client=client,
                        marketplace_code=marketplace_code,
                        asins=batch,
                        period_start=period_start,
                        period_end=period_end,
                        period_type=period_type,
                        region=region,
                        marketplace_id=marketplace_id
                    )

                # Upsert immediately per-batch (prevents data loss on later failure)
                if rows:
                    if report_type == "SQP":
                        upsert_sqp_data(rows)
                    else:
                        upsert_scp_data(rows)
                    total_rows_upserted += len(rows)

                batch_status[batch_key] = "completed"
                result["completed_batches"] += 1
                print(f"{len(rows)} rows (upserted)")

                # Update tracking after each batch (for resume)
                update_sqp_pull_status(
                    pull_id,
                    batch_status=batch_status,
                    completed_batches=result["completed_batches"],
                    total_rows=total_rows_upserted
                )

            except RuntimeError as e:
                # Report FATAL/CANCELLED - record but continue
                error_msg = str(e)
                batch_status[batch_key] = "failed"
                result["failed_batches"] += 1
                print(f"FAILED: {error_msg}")

                # Track which ASINs failed
                for asin in batch:
                    record_asin_error(marketplace_code, asin, "REPORT_FATAL", error_msg)

                update_sqp_pull_status(
                    pull_id,
                    batch_status=batch_status,
                    failed_batches=result["failed_batches"],
                    error_count=result["failed_batches"]
                )

            except SPAPIError as e:
                error_msg = str(e)
                batch_status[batch_key] = "failed"
                result["failed_batches"] += 1
                print(f"API ERROR: {error_msg}")

                for asin in batch:
                    record_asin_error(marketplace_code, asin, "API_ERROR", error_msg)

                update_sqp_pull_status(
                    pull_id,
                    batch_status=batch_status,
                    failed_batches=result["failed_batches"],
                    error_message=error_msg,
                    error_count=result["failed_batches"]
                )

        # Determine final status
        processing_time_ms = int((time.time() - start_time) * 1000)

        if result["failed_batches"] == 0:
            final_status = "completed"
        elif result["completed_batches"] > 0:
            final_status = "partial"
        else:
            final_status = "failed"

        result["status"] = final_status
        result["total_rows"] = total_rows_upserted
        result["total_queries"] = total_queries

        # Update pull record with final status
        update_sqp_pull_status(
            pull_id,
            status=final_status,
            batch_status=batch_status,
            completed_batches=result["completed_batches"],
            failed_batches=result["failed_batches"],
            total_rows=total_rows_upserted,
            total_queries=total_queries,
            processing_time_ms=processing_time_ms
        )

        status_emoji = {"completed": "OK", "partial": "PARTIAL", "failed": "FAILED"}.get(final_status, "?")
        print(f"  [{status_emoji}] {marketplace_code} {report_type}: {total_rows_upserted} rows, {result['completed_batches']}/{len(batches)} batches in {processing_time_ms/1000:.1f}s")

    except Exception as e:
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg
        logger.error(f"{marketplace_code} {report_type} failed: {error_msg}")
        print(f"  FAILED: {error_msg}")
        alert_failure("sqp_pull", marketplace_code, error_msg, 0)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Pull SQP/SCP search performance data from Amazon SP-API"
    )
    parser.add_argument(
        "--report-type",
        type=str,
        choices=["SQP", "SCP", "both"],
        default="both",
        help="Report type to pull (default: both)"
    )
    parser.add_argument(
        "--period-type",
        type=str,
        choices=["WEEK", "MONTH"],
        default="WEEK",
        help="Period granularity (default: WEEK)"
    )
    parser.add_argument(
        "--period-start",
        type=str,
        help="Period start date (YYYY-MM-DD). Must align to period boundaries."
    )
    parser.add_argument(
        "--period-end",
        type=str,
        help="Period end date (YYYY-MM-DD). Must align to period boundaries."
    )
    parser.add_argument(
        "--marketplace",
        type=str,
        help="Specific marketplace code (e.g., USA, UK, AU). Omit for all in region."
    )
    parser.add_argument(
        "--region",
        type=str,
        default="NA",
        choices=["NA", "EU", "FE", "UAE"],
        help="Region (default: NA)"
    )
    parser.add_argument("--resume", action="store_true", default=True, help="Resume interrupted pull (default: True)")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh, don't resume")
    parser.add_argument("--force", action="store_true", help="Force re-pull even if data exists")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be pulled without pulling")

    args = parser.parse_args()
    resume = args.resume and not args.no_resume

    # Determine period
    if args.period_start and args.period_end:
        period_start = date.fromisoformat(args.period_start)
        period_end = date.fromisoformat(args.period_end)
    elif args.period_type == "WEEK":
        period_start, period_end = get_latest_available_week()
    else:
        period_start, period_end = get_latest_available_month()

    # Determine report types
    if args.report_type == "both":
        report_types = ["SQP", "SCP"]
    else:
        report_types = [args.report_type]

    # Determine marketplaces
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    else:
        marketplaces = MARKETPLACES_BY_REGION.get(args.region.upper(), ["USA", "CA"])

    print(f"\nSP-API SQP/SCP Pull Script")
    print(f"Period: {args.period_type} {period_start} to {period_end}")
    print(f"Reports: {', '.join(report_types)}")
    print(f"Marketplaces: {', '.join(marketplaces)}")
    print(f"Resume: {resume} | Force: {args.force} | Dry-run: {args.dry_run}")
    print(f"{'='*60}")

    # Get access token and create client
    if not args.dry_run:
        print("Getting access token...")
        access_token = get_access_token(region=args.region)
        client = SPAPIClient(access_token, region=args.region)
    else:
        client = None

    all_results = []

    for marketplace_code in marketplaces:
        print(f"\n--- {marketplace_code} ---")
        for report_type in report_types:
            result = pull_for_marketplace(
                client=client,
                marketplace_code=marketplace_code,
                report_type=report_type,
                period_start=period_start,
                period_end=period_end,
                period_type=args.period_type,
                region=args.region,
                resume=resume,
                force=args.force,
                dry_run=args.dry_run
            )
            all_results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    completed = sum(1 for r in all_results if r["status"] == "completed")
    skipped = sum(1 for r in all_results if r["status"] == "skipped")
    partial = sum(1 for r in all_results if r["status"] == "partial")
    failed = sum(1 for r in all_results if r["status"] == "failed")
    dry_run_count = sum(1 for r in all_results if r["status"] == "dry_run")
    total_rows = sum(r["total_rows"] for r in all_results)

    for r in all_results:
        status_icon = {
            "completed": "OK", "skipped": "SKIP", "partial": "PART",
            "failed": "FAIL", "dry_run": "DRY"
        }.get(r["status"], "?")
        print(f"  [{status_icon}] {r['marketplace']} {r['report_type']}: {r['total_rows']} rows, {r['completed_batches']}/{r['total_batches']} batches")
        if r.get("error"):
            print(f"         Error: {r['error'][:100]}")

    print(f"\nTotal: {completed} completed, {skipped} skipped, {partial} partial, {failed} failed")
    if dry_run_count:
        print(f"Dry-run: {dry_run_count} operations previewed")
    print(f"Total rows: {total_rows}")

    # Send alerts if failures
    if failed > 0:
        failed_list = [f"{r['marketplace']} {r['report_type']}" for r in all_results if r["status"] == "failed"]
        completed_list = [f"{r['marketplace']} {r['report_type']}" for r in all_results if r["status"] == "completed"]
        errors = {f"{r['marketplace']} {r['report_type']}": r.get("error", "Unknown")
                  for r in all_results if r["status"] == "failed"}
        alert_partial("sqp_pull", f"{period_start}", completed_list, failed_list, errors)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
