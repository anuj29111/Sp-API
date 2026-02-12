#!/usr/bin/env python3
"""
SP-API Gap Detection & Auto-Repair Script

Detects missing or failed daily S&T pulls and automatically backfills them.
Designed to run daily after the main pull, or on-demand.

How it works:
1. For each marketplace, generates a series of expected dates
2. Compares against sp_api_pulls to find dates with no successful pull
3. Automatically re-pulls any gaps found (up to configurable limit)
4. Sends Slack alert with gap report

Usage:
    python scripts/detect_gaps.py                          # Check last 45 days, all regions
    python scripts/detect_gaps.py --days 90                # Check last 90 days
    python scripts/detect_gaps.py --region NA              # Check only NA region
    python scripts/detect_gaps.py --marketplace USA        # Check only USA
    python scripts/detect_gaps.py --dry-run                # Report gaps without fixing
    python scripts/detect_gaps.py --max-repairs 5          # Limit repairs per run

Environment Variables Required:
    SP_LWA_CLIENT_ID, SP_LWA_CLIENT_SECRET
    SP_REFRESH_TOKEN_NA (and EU/FE/UAE as needed)
    SUPABASE_URL, SUPABASE_SERVICE_KEY

Optional:
    SLACK_WEBHOOK_URL - Sends gap report to Slack
"""

import os
import sys
import argparse
import logging
from datetime import date, timedelta
from typing import List, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.db import get_supabase_client, MARKETPLACE_UUIDS, AMAZON_MARKETPLACE_IDS
from scripts.utils.auth import get_access_token
from scripts.utils.api_client import SPAPIClient
from scripts.utils.alerting import get_alert_manager

# Import pull function directly
from scripts.pull_daily_sales import pull_marketplace_data, MARKETPLACES_BY_REGION

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default lookback window (days)
DEFAULT_LOOKBACK_DAYS = 45

# Max gaps to repair in a single run (to avoid hitting API rate limits)
DEFAULT_MAX_REPAIRS = 10

# Region for each marketplace
MARKETPLACE_REGION = {}
for region, mps in MARKETPLACES_BY_REGION.items():
    for mp in mps:
        MARKETPLACE_REGION[mp] = region


def detect_gaps(
    marketplace_code: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    end_date: date = None
) -> List[Dict]:
    """
    Detect missing or failed S&T pulls for a marketplace.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        lookback_days: How many days back to check
        end_date: End date for the check window (default: yesterday)

    Returns:
        List of dicts with {date, marketplace, last_status, last_error} for each gap
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    if end_date is None:
        end_date = date.today() - timedelta(days=1)  # Yesterday (today not available yet)

    start_date = end_date - timedelta(days=lookback_days - 1)

    # Get all pull records for this marketplace in the date range
    result = client.table("sp_api_pulls").select(
        "pull_date, status, asin_count, error_message, started_at"
    ).eq(
        "marketplace_id", marketplace_id
    ).gte(
        "pull_date", start_date.isoformat()
    ).lte(
        "pull_date", end_date.isoformat()
    ).order(
        "pull_date"
    ).order(
        "started_at", desc=True
    ).execute()

    # Build lookup: for each date, track the best pull status
    successful_dates = set()
    latest_by_date = {}  # date_str -> {status, error_message}

    for row in (result.data or []):
        pull_date = row["pull_date"]

        # Track successful pulls
        if row["status"] == "completed" and (row.get("asin_count") or 0) > 0:
            successful_dates.add(pull_date)

        # Track latest attempt per date (first seen = most recent due to order)
        if pull_date not in latest_by_date:
            latest_by_date[pull_date] = {
                "status": row["status"],
                "error_message": row.get("error_message"),
                "started_at": row.get("started_at")
            }

    # Generate expected dates and find gaps
    gaps = []
    current = start_date
    while current <= end_date:
        date_str = current.isoformat()
        if date_str not in successful_dates:
            latest = latest_by_date.get(date_str, {})
            gaps.append({
                "date": date_str,
                "marketplace": marketplace_code,
                "last_status": latest.get("status"),
                "last_error": latest.get("error_message"),
                "last_attempt": latest.get("started_at")
            })
        current += timedelta(days=1)

    return gaps


def repair_gaps(
    gaps: List[Dict],
    max_repairs: int = DEFAULT_MAX_REPAIRS,
    dry_run: bool = False
) -> Dict:
    """
    Attempt to re-pull data for detected gaps.

    Args:
        gaps: List of gap dicts from detect_gaps()
        max_repairs: Max number of gaps to repair in this run
        dry_run: If True, only report gaps without fixing

    Returns:
        Summary dict with counts
    """
    if not gaps:
        return {"total_gaps": 0, "repaired": 0, "failed": 0, "skipped": 0}

    # Sort by date (oldest first — most important to fix)
    gaps_to_fix = sorted(gaps, key=lambda g: g["date"])[:max_repairs]
    remaining = len(gaps) - len(gaps_to_fix)

    summary = {
        "total_gaps": len(gaps),
        "attempted": len(gaps_to_fix),
        "repaired": 0,
        "failed": 0,
        "skipped": 0,
        "remaining": remaining,
        "details": []
    }

    if dry_run:
        logger.info(f"DRY RUN: Would repair {len(gaps_to_fix)} gaps (of {len(gaps)} total)")
        for gap in gaps_to_fix:
            detail = {
                "marketplace": gap["marketplace"],
                "date": gap["date"],
                "status": "dry_run",
                "last_status": gap.get("last_status"),
                "last_error": gap.get("last_error")
            }
            summary["details"].append(detail)
            summary["skipped"] += 1
        return summary

    # Group gaps by region to reuse auth tokens
    by_region = {}
    for gap in gaps_to_fix:
        region = MARKETPLACE_REGION.get(gap["marketplace"], "NA")
        if region not in by_region:
            by_region[region] = []
        by_region[region].append(gap)

    for region, region_gaps in by_region.items():
        logger.info(f"Repairing {len(region_gaps)} gaps in {region} region")

        try:
            access_token = get_access_token(region=region)
            client = SPAPIClient(access_token, region=region)
        except Exception as e:
            logger.error(f"Failed to authenticate for {region}: {e}")
            for gap in region_gaps:
                summary["details"].append({
                    "marketplace": gap["marketplace"],
                    "date": gap["date"],
                    "status": "auth_failed",
                    "error": str(e)
                })
                summary["failed"] += 1
            continue

        for gap in region_gaps:
            mp_code = gap["marketplace"]
            gap_date = date.fromisoformat(gap["date"]) if isinstance(gap["date"], str) else gap["date"]

            logger.info(f"Repairing {mp_code} {gap_date}...")

            try:
                result = pull_marketplace_data(
                    marketplace_code=mp_code,
                    report_date=gap_date,
                    region=region,
                    skip_existing=False,  # Force re-pull
                    client=client
                )

                if result["status"] == "completed":
                    summary["repaired"] += 1
                    logger.info(f"  Repaired: {mp_code} {gap_date} ({result['asin_count']} ASINs)")
                else:
                    summary["failed"] += 1
                    logger.error(f"  Failed: {mp_code} {gap_date} — {result.get('error', 'Unknown')}")

                summary["details"].append({
                    "marketplace": mp_code,
                    "date": gap_date.isoformat(),
                    "status": result["status"],
                    "asin_count": result.get("asin_count", 0),
                    "error": result.get("error")
                })

            except Exception as e:
                summary["failed"] += 1
                logger.error(f"  Exception repairing {mp_code} {gap_date}: {e}")
                summary["details"].append({
                    "marketplace": mp_code,
                    "date": gap_date.isoformat(),
                    "status": "exception",
                    "error": str(e)
                })

    return summary


def send_gap_report(all_gaps: Dict[str, List], repair_summary: Dict, dry_run: bool):
    """Send gap detection report to Slack and console."""
    alert = get_alert_manager()

    total_gaps = sum(len(gaps) for gaps in all_gaps.values())
    gap_marketplaces = {mp for mp, gaps in all_gaps.items() if gaps}

    # Console report
    print(f"\n{'='*60}")
    print(f"  SP-API GAP DETECTION REPORT")
    print(f"{'='*60}")

    if total_gaps == 0:
        print(f"\n  No gaps detected. All data is complete.")
        print(f"{'='*60}\n")
        return

    print(f"\n  Total gaps found: {total_gaps}")
    print(f"  Affected marketplaces: {', '.join(sorted(gap_marketplaces))}")

    for mp, gaps in sorted(all_gaps.items()):
        if gaps:
            print(f"\n  {mp}:")
            for gap in gaps:
                status = gap.get("last_status", "never_pulled")
                print(f"    - {gap['date']}  (last: {status})")

    if repair_summary:
        print(f"\n  Repair Results:")
        print(f"    Attempted: {repair_summary['attempted']}")
        print(f"    Repaired:  {repair_summary['repaired']}")
        print(f"    Failed:    {repair_summary['failed']}")
        if repair_summary.get('remaining', 0) > 0:
            print(f"    Remaining: {repair_summary['remaining']} (will be fixed in next run)")

    print(f"{'='*60}\n")

    # Slack report
    if not alert.slack_webhook:
        return

    color = "#00FF00" if total_gaps == 0 else ("#FFA500" if repair_summary.get("repaired", 0) > 0 else "#FF0000")
    mode = "DRY RUN" if dry_run else "AUTO-REPAIR"

    gap_lines = []
    for mp, gaps in sorted(all_gaps.items()):
        if gaps:
            dates = [g["date"] for g in gaps[:5]]
            suffix = f" (+{len(gaps)-5} more)" if len(gaps) > 5 else ""
            gap_lines.append(f"*{mp}*: {', '.join(dates)}{suffix}")

    repair_text = ""
    if repair_summary and not dry_run:
        repair_text = f"\n*Repairs*: {repair_summary['repaired']}/{repair_summary['attempted']} successful"

    import requests
    import json
    payload = {
        "attachments": [{
            "color": color,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"SP-API Gap Detection [{mode}]", "emoji": True}
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Gaps Found:* {total_gaps}\n" + "\n".join(gap_lines) + repair_text
                    }
                }
            ]
        }]
    }

    try:
        requests.post(alert.slack_webhook, json=payload, timeout=10)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Detect and repair missing SP-API daily data pulls"
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
        help=f"Days to look back (default: {DEFAULT_LOOKBACK_DAYS})"
    )
    parser.add_argument(
        "--region", type=str, choices=["NA", "EU", "FE", "UAE"],
        help="Check specific region only"
    )
    parser.add_argument(
        "--marketplace", type=str,
        help="Check specific marketplace only (e.g., USA, UK)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report gaps without repairing"
    )
    parser.add_argument(
        "--max-repairs", type=int, default=DEFAULT_MAX_REPAIRS,
        help=f"Max gaps to repair per run (default: {DEFAULT_MAX_REPAIRS})"
    )
    parser.add_argument(
        "--end-date", type=str,
        help="End date for check window (YYYY-MM-DD, default: yesterday)"
    )

    args = parser.parse_args()

    end_date = date.fromisoformat(args.end_date) if args.end_date else None

    # Determine which marketplaces to check
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    elif args.region:
        marketplaces = MARKETPLACES_BY_REGION.get(args.region.upper(), [])
    else:
        # All marketplaces
        marketplaces = []
        for region_mps in MARKETPLACES_BY_REGION.values():
            marketplaces.extend(region_mps)

    print(f"\nSP-API Gap Detector")
    print(f"  Lookback: {args.days} days")
    print(f"  Marketplaces: {', '.join(marketplaces)}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else f'AUTO-REPAIR (max {args.max_repairs})'}")

    # Detect gaps for each marketplace
    all_gaps = {}
    combined_gaps = []

    for mp_code in marketplaces:
        logger.info(f"Checking {mp_code}...")
        gaps = detect_gaps(mp_code, lookback_days=args.days, end_date=end_date)
        all_gaps[mp_code] = gaps
        combined_gaps.extend(gaps)

        if gaps:
            logger.warning(f"  {mp_code}: {len(gaps)} gap(s) found")
            for gap in gaps:
                logger.warning(f"    {gap['date']} (last: {gap.get('last_status', 'never')})")
        else:
            logger.info(f"  {mp_code}: No gaps")

    # Repair gaps
    repair_summary = {}
    if combined_gaps and not args.dry_run:
        repair_summary = repair_gaps(combined_gaps, max_repairs=args.max_repairs)
    elif combined_gaps and args.dry_run:
        repair_summary = repair_gaps(combined_gaps, dry_run=True)

    # Send report
    send_gap_report(all_gaps, repair_summary, args.dry_run)

    # Exit code: 0 if no unrepaired gaps, 1 if gaps remain
    total_gaps = len(combined_gaps)
    repaired = repair_summary.get("repaired", 0) if repair_summary else 0

    if total_gaps == 0:
        print("All clear — no gaps detected.")
        sys.exit(0)
    elif total_gaps == repaired:
        print(f"All {repaired} gap(s) repaired successfully.")
        sys.exit(0)
    elif args.dry_run:
        print(f"{total_gaps} gap(s) detected (dry run, no repairs attempted).")
        sys.exit(1)
    else:
        remaining = total_gaps - repaired
        print(f"{remaining} gap(s) remain after repair attempt.")
        sys.exit(1)


if __name__ == "__main__":
    main()
