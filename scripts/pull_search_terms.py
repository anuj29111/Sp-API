#!/usr/bin/env python3
"""
SP-API Brand Analytics Search Terms Report Pull Script

Pulls the Search Terms Report (top 3 clicked ASINs per search term across the
entire marketplace), filters to only terms matching existing SQP data, and stores
the results.

This gives us competitive intelligence: for each keyword we compete on, who are
the top 3 competitors and their click/conversion share.

The report is massive (~12M rows, ~2.3 GB) but we stream-parse it and only keep
rows matching our SQP keywords (~4-5K terms → ~12-15K rows per marketplace).

Usage:
    python pull_search_terms.py                              # Latest week, USA only
    python pull_search_terms.py --marketplace USA            # Single marketplace
    python pull_search_terms.py --region NA                  # All NA marketplaces
    python pull_search_terms.py --period-start 2026-02-02 --period-end 2026-02-08
    python pull_search_terms.py --dry-run                    # Show what would be pulled
    python pull_search_terms.py --force                      # Force re-pull even if data exists
    python pull_search_terms.py --fallback                   # Use memory-based download (debugging)
"""

import os
import sys
import argparse
import time
import logging
from datetime import date, datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.auth import get_access_token
from scripts.utils.api_client import SPAPIClient, SPAPIError
from scripts.utils.alerting import alert_failure, alert_partial, send_summary
from scripts.utils.db import (
    MARKETPLACE_UUIDS,
    get_sqp_keywords_for_matching,
    upsert_search_terms_data,
    create_search_terms_pull_record,
    update_search_terms_pull_status,
    get_existing_search_terms_pull,
)
from scripts.utils.search_terms_reports import (
    create_search_terms_report,
    get_report_download_info,
    stream_and_filter_search_terms,
    download_and_filter_fallback,
)
from scripts.utils.sqp_reports import (
    get_latest_available_week,
    get_latest_available_month,
    poll_report_status,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Marketplaces by region for Brand Analytics
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
    period_start: date,
    period_end: date,
    period_type: str,
    region: str,
    force: bool = False,
    dry_run: bool = False,
    use_fallback: bool = False
) -> dict:
    """
    Pull Search Terms Report for a single marketplace.

    Flow:
    1. Check if pull already exists (skip if completed and not force)
    2. Load SQP keywords for matching
    3. Create report request
    4. Poll until done
    5. Stream-parse and filter
    6. Upsert matched rows

    Args:
        client: SPAPIClient instance
        marketplace_code: e.g., 'USA'
        period_start/period_end: Period boundaries
        period_type: 'WEEK', 'MONTH', etc.
        region: API region
        force: Re-pull even if data exists
        dry_run: Preview mode
        use_fallback: Use memory-based download instead of streaming

    Returns:
        Dict with status, counts, and error info
    """
    result = {
        "marketplace": marketplace_code,
        "status": "pending",
        "sqp_keywords": 0,
        "matched_terms": 0,
        "total_rows": 0,
        "error": None
    }

    try:
        # Step 1: Check existing pull
        existing = get_existing_search_terms_pull(
            marketplace_code, period_start, period_end, period_type
        )
        if existing and existing["status"] == "completed" and not force:
            result["status"] = "skipped"
            result["matched_terms"] = existing.get("matched_terms_count", 0)
            result["total_rows"] = existing.get("total_rows", 0)
            print(f"  Already completed ({result['total_rows']} rows). Use --force to re-pull.")
            return result

        # Step 2: Load SQP keywords for filtering
        print(f"  Loading SQP keywords for matching...")
        sqp_keywords = get_sqp_keywords_for_matching(
            marketplace_code, period_start, period_end, period_type
        )
        result["sqp_keywords"] = len(sqp_keywords)

        if not sqp_keywords:
            result["status"] = "skipped"
            print(f"  No SQP keywords found — skipping (nothing to match against)")
            return result

        if dry_run:
            result["status"] = "dry_run"
            print(f"  DRY RUN: Would pull Search Terms Report and filter against {len(sqp_keywords)} SQP keywords")
            return result

        # Step 3: Create pull tracking record
        start_time = time.time()
        pull_id = create_search_terms_pull_record(
            marketplace_code, period_start, period_end, period_type, len(sqp_keywords)
        )

        # Step 4: Request the report from Amazon
        print(f"  Requesting Search Terms Report from SP-API...")
        report_id = create_search_terms_report(
            client, marketplace_code, period_start, period_end, period_type, region
        )

        update_search_terms_pull_status(pull_id, report_id=report_id)

        # Step 5: Poll until report is ready (up to 15 minutes — large report)
        print(f"  Polling for report completion (max 15 min)...")
        poll_result = poll_report_status(
            client, report_id, region=region,
            max_wait_seconds=900,  # 15 minutes
            poll_interval=30       # Check every 30 seconds (large report, no rush)
        )

        report_document_id = poll_result["reportDocumentId"]
        update_search_terms_pull_status(pull_id, report_document_id=report_document_id)
        print(f"  Report ready (document: {report_document_id[:20]}...)")

        # Step 6: Get download URL
        download_info = get_report_download_info(client, report_document_id, region)
        download_url = download_info["url"]
        compression = download_info["compressionAlgorithm"]

        # Step 7: Stream-parse, filter, and upsert
        marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

        if use_fallback:
            matched_terms, total_rows = download_and_filter_fallback(
                download_url=download_url,
                compression=compression,
                sqp_keywords_set=sqp_keywords,
                marketplace_id=marketplace_id,
                period_start=period_start,
                period_end=period_end,
                period_type=period_type,
                upsert_callback=upsert_search_terms_data,
                batch_size=200
            )
        else:
            matched_terms, total_rows = stream_and_filter_search_terms(
                download_url=download_url,
                compression=compression,
                sqp_keywords_set=sqp_keywords,
                marketplace_id=marketplace_id,
                period_start=period_start,
                period_end=period_end,
                period_type=period_type,
                upsert_callback=upsert_search_terms_data,
                batch_size=200
            )

        # Step 8: Update tracking with results
        processing_time_ms = int((time.time() - start_time) * 1000)

        result["status"] = "completed"
        result["matched_terms"] = matched_terms
        result["total_rows"] = total_rows

        update_search_terms_pull_status(
            pull_id,
            status="completed",
            matched_terms_count=matched_terms,
            total_rows=total_rows,
            processing_time_ms=processing_time_ms
        )

        match_rate = (matched_terms / len(sqp_keywords) * 100) if sqp_keywords else 0
        print(f"  [OK] {marketplace_code}: {matched_terms} terms matched ({match_rate:.1f}% of SQP), {total_rows} rows in {processing_time_ms/1000:.1f}s")

    except Exception as e:
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg
        logger.error(f"{marketplace_code} Search Terms failed: {error_msg}")
        print(f"  FAILED: {error_msg}")

        # Update tracking if we have a pull_id
        try:
            if 'pull_id' in locals():
                processing_time_ms = int((time.time() - start_time) * 1000)
                update_search_terms_pull_status(
                    pull_id,
                    status="failed",
                    error_message=error_msg[:1000],
                    processing_time_ms=processing_time_ms
                )
        except Exception:
            pass

        alert_failure("search_terms_pull", marketplace_code, error_msg, 0)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Pull Brand Analytics Search Terms Report from Amazon SP-API"
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
        help="Specific marketplace code (e.g., USA, UK, AU). Default: USA only."
    )
    parser.add_argument(
        "--region",
        type=str,
        default="NA",
        choices=["NA", "EU", "FE", "UAE"],
        help="Region (default: NA)"
    )
    parser.add_argument("--force", action="store_true", help="Force re-pull even if data exists")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be pulled without pulling")
    parser.add_argument("--fallback", action="store_true", help="Use memory-based download (debugging only)")

    args = parser.parse_args()

    # Determine period
    if args.period_start and args.period_end:
        period_start = date.fromisoformat(args.period_start)
        period_end = date.fromisoformat(args.period_end)
    elif args.period_type == "WEEK":
        period_start, period_end = get_latest_available_week()
    else:
        period_start, period_end = get_latest_available_month()

    # Determine marketplaces
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    else:
        marketplaces = MARKETPLACES_BY_REGION.get(args.region.upper(), ["USA"])

    print(f"\nSP-API Search Terms Report Pull")
    print(f"Period: {args.period_type} {period_start} to {period_end}")
    print(f"Marketplaces: {', '.join(marketplaces)}")
    print(f"Force: {args.force} | Dry-run: {args.dry_run} | Fallback: {args.fallback}")
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
        result = pull_for_marketplace(
            client=client,
            marketplace_code=marketplace_code,
            period_start=period_start,
            period_end=period_end,
            period_type=args.period_type,
            region=args.region,
            force=args.force,
            dry_run=args.dry_run,
            use_fallback=args.fallback
        )
        all_results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    completed = sum(1 for r in all_results if r["status"] == "completed")
    skipped = sum(1 for r in all_results if r["status"] == "skipped")
    failed = sum(1 for r in all_results if r["status"] == "failed")
    dry_run_count = sum(1 for r in all_results if r["status"] == "dry_run")
    total_rows = sum(r["total_rows"] for r in all_results)

    for r in all_results:
        status_icon = {
            "completed": "OK", "skipped": "SKIP",
            "failed": "FAIL", "dry_run": "DRY"
        }.get(r["status"], "?")
        sqp_info = f"{r['sqp_keywords']} SQP keywords" if r["sqp_keywords"] else ""
        match_info = f"{r['matched_terms']} matched" if r["matched_terms"] else ""
        row_info = f"{r['total_rows']} rows"
        print(f"  [{status_icon}] {r['marketplace']}: {sqp_info}, {match_info}, {row_info}")
        if r.get("error"):
            print(f"         Error: {r['error'][:100]}")

    print(f"\nTotal: {completed} completed, {skipped} skipped, {failed} failed")
    if dry_run_count:
        print(f"Dry-run: {dry_run_count} operations previewed")
    print(f"Total rows: {total_rows}")

    # Send alerts if failures
    if failed > 0:
        failed_list = [r['marketplace'] for r in all_results if r["status"] == "failed"]
        completed_list = [r['marketplace'] for r in all_results if r["status"] == "completed"]
        errors = {r['marketplace']: r.get("error", "Unknown")
                  for r in all_results if r["status"] == "failed"}
        alert_partial("search_terms_pull", f"{period_start}", completed_list, failed_list, errors)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
