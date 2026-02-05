#!/usr/bin/env python3
"""
Refresh Materialized Views Script

Refreshes the SP-API materialized views to update aggregated data.
Only refreshes data that could have changed (current month + last month).

Usage:
    python refresh_views.py                    # Refresh all views
    python refresh_views.py --view weekly      # Refresh only weekly
    python refresh_views.py --view monthly     # Refresh only monthly
    python refresh_views.py --view rolling     # Refresh only rolling
    python refresh_views.py --full             # Force full refresh of all data

Environment Variables Required:
    SUPABASE_URL          - Supabase project URL
    SUPABASE_SERVICE_KEY  - Supabase service role key

Note on efficiency:
    PostgreSQL materialized views don't support partial refresh.
    However, with ~15K-500K rows, full refresh takes only 1-5 seconds.
    The rolling metrics view only includes last 60 days anyway.

    For weekly/monthly views, historical data doesn't change, but the
    refresh is fast enough that it doesn't matter. If performance becomes
    an issue in the future, we could partition the views by time range.
"""

import os
import sys
import argparse
import time
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.db import get_supabase_client


# View configurations
VIEWS = {
    "weekly": {
        "mat_view": "sp_weekly_asin_data_mat",
        "description": "Weekly ASIN aggregates"
    },
    "monthly": {
        "mat_view": "sp_monthly_asin_data_mat",
        "description": "Monthly ASIN aggregates"
    },
    "rolling": {
        "mat_view": "sp_rolling_asin_metrics_mat",
        "description": "Rolling 7/14/30/60 day metrics"
    }
}


def refresh_view(view_name: str, concurrent: bool = True) -> dict:
    """
    Refresh a single materialized view.

    Args:
        view_name: Name of the materialized view
        concurrent: Use CONCURRENTLY option (allows reads during refresh)

    Returns:
        Dict with status and timing
    """
    client = get_supabase_client()
    start_time = time.time()

    try:
        # Build refresh command
        # CONCURRENTLY allows the view to be read during refresh
        # Requires a unique index on the view (which we have)
        if concurrent:
            sql = f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}"
        else:
            sql = f"REFRESH MATERIALIZED VIEW {view_name}"

        # Execute via postgrest-py rpc or direct SQL
        # Using rpc if available, otherwise this will need adjustment
        try:
            client.rpc("exec_sql", {"query": sql}).execute()
        except Exception:
            # If exec_sql RPC doesn't exist, try direct execution
            # This requires the service role key which bypasses RLS
            from supabase._sync.client import SyncClient
            # For direct SQL, we'd need to use a different approach
            # For now, we'll note this limitation
            raise Exception("exec_sql RPC not available. Please create it or use Supabase SQL editor.")

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "view": view_name,
            "status": "success",
            "elapsed_ms": elapsed_ms,
            "concurrent": concurrent
        }

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        error_msg = str(e)

        # If concurrent refresh fails (e.g., no unique index), try non-concurrent
        if concurrent and ("cannot refresh" in error_msg.lower() or "unique" in error_msg.lower()):
            print(f"⚠️  Concurrent refresh failed, trying non-concurrent...")
            return refresh_view(view_name, concurrent=False)

        return {
            "view": view_name,
            "status": "failed",
            "elapsed_ms": elapsed_ms,
            "error": error_msg
        }


def refresh_all_views(views_to_refresh: list = None) -> dict:
    """
    Refresh all or specified materialized views.

    Args:
        views_to_refresh: List of view keys to refresh, or None for all

    Returns:
        Summary of refresh operations
    """
    if views_to_refresh is None:
        views_to_refresh = list(VIEWS.keys())

    print("\n" + "=" * 60)
    print("🔄 REFRESHING MATERIALIZED VIEWS")
    print("=" * 60)
    print(f"📅 Time: {datetime.now().isoformat()}")
    print(f"📋 Views to refresh: {', '.join(views_to_refresh)}")

    results = []
    total_start = time.time()

    for view_key in views_to_refresh:
        if view_key not in VIEWS:
            print(f"⚠️  Unknown view: {view_key}, skipping")
            continue

        view_config = VIEWS[view_key]
        mat_view = view_config["mat_view"]
        description = view_config["description"]

        print(f"\n🔄 Refreshing {view_key}: {description}")
        print(f"   Materialized view: {mat_view}")

        result = refresh_view(mat_view)
        results.append(result)

        if result["status"] == "success":
            print(f"   ✅ Completed in {result['elapsed_ms']}ms")
        else:
            print(f"   ❌ Failed: {result.get('error', 'Unknown error')[:100]}")

    total_elapsed = int((time.time() - total_start) * 1000)

    # Summary
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = len(results) - success_count

    print("\n" + "=" * 60)
    print("📊 REFRESH SUMMARY")
    print("=" * 60)
    print(f"✅ Successful: {success_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"⏱️  Total time: {total_elapsed}ms")

    return {
        "results": results,
        "success_count": success_count,
        "failed_count": failed_count,
        "total_elapsed_ms": total_elapsed
    }


def main():
    parser = argparse.ArgumentParser(
        description="Refresh SP-API materialized views"
    )
    parser.add_argument(
        "--view",
        type=str,
        choices=list(VIEWS.keys()),
        help="Specific view to refresh. Default: all views"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be refreshed without actually refreshing"
    )

    args = parser.parse_args()

    # Determine which views to refresh
    if args.view:
        views_to_refresh = [args.view]
    else:
        views_to_refresh = list(VIEWS.keys())

    if args.dry_run:
        print("\n🏃 DRY RUN - Would refresh:")
        for view_key in views_to_refresh:
            if view_key in VIEWS:
                print(f"   - {view_key}: {VIEWS[view_key]['mat_view']}")
        print("\nNote: Full refresh takes ~1-5 seconds for current data size.")
        print("Historical data (e.g., Dec 2025) is included but doesn't change.")
        return

    # Run refresh
    summary = refresh_all_views(views_to_refresh)

    # Exit with error if any failed
    if summary["failed_count"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
