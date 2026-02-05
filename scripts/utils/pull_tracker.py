"""
Pull Tracker Module
Tracks pull progress with checkpoint and resume capability.

Features:
- Per-marketplace status tracking
- Checkpoint data for resume on failure
- Automatic status updates in sp_pull_checkpoints table
"""

import os
import json
import logging
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from supabase import create_client

logger = logging.getLogger(__name__)


def get_supabase_client():
    """Get Supabase client."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


class PullTracker:
    """
    Enhanced pull tracking with resume capability.

    Tracks:
    - Overall pull status (pending, in_progress, partial, completed, failed)
    - Individual marketplace status within a pull
    - Checkpoints for multi-step operations
    - Retry counts and error history

    Usage:
        tracker = PullTracker("sales_traffic", date.today())
        tracker.start_pull()

        for marketplace in marketplaces:
            tracker.start_marketplace(marketplace)
            try:
                # ... do work ...
                tracker.complete_marketplace(marketplace, row_count=150)
            except Exception as e:
                tracker.fail_marketplace(marketplace, str(e))

        tracker.finish_pull()
    """

    def __init__(
        self,
        pull_type: str,
        pull_date: date,
        region: str = "NA"
    ):
        """
        Initialize pull tracker.

        Args:
            pull_type: Type of pull ('sales_traffic', 'fba_inventory', 'awd_inventory', 'storage_fees')
            pull_date: Date being pulled
            region: API region ('NA', 'EU', 'FE')
        """
        self.pull_type = pull_type
        self.pull_date = pull_date
        self.region = region

        self.pull_id: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.marketplace_status: Dict[str, Dict] = {}
        self.checkpoint_data: Dict[str, Any] = {}
        self.error_count: int = 0
        self.last_error: Optional[str] = None
        self.total_row_count: int = 0

        self._client = None

    @property
    def client(self):
        """Lazy-load Supabase client."""
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    def start_pull(self, resume: bool = True) -> str:
        """
        Start or resume a pull operation.

        Args:
            resume: If True, check for existing incomplete pull to resume

        Returns:
            Pull ID (UUID)
        """
        self.started_at = datetime.utcnow()

        # Check for existing pull to resume
        if resume:
            existing = self._get_existing_pull()
            if existing and existing.get("status") in ["in_progress", "partial"]:
                self.pull_id = existing["id"]
                self.marketplace_status = existing.get("marketplace_status", {})
                self.checkpoint_data = existing.get("checkpoint_data", {})
                self.error_count = existing.get("error_count", 0)
                logger.info(f"Resuming pull {self.pull_id} from checkpoint")
                self._update_status("in_progress")
                return self.pull_id

        # Create new pull record (upsert to handle duplicate dates)
        result = self.client.table("sp_pull_checkpoints").upsert({
            "pull_type": self.pull_type,
            "pull_date": self.pull_date.isoformat(),
            "region": self.region,
            "status": "in_progress",
            "started_at": self.started_at.isoformat(),
            "marketplace_status": {},
            "checkpoint_data": {},
            "error_count": 0
        }, on_conflict="pull_type,pull_date,region").execute()

        self.pull_id = result.data[0]["id"]
        logger.info(f"Started new pull {self.pull_id} for {self.pull_type} on {self.pull_date}")
        return self.pull_id

    def _get_existing_pull(self) -> Optional[dict]:
        """Get existing pull record if any."""
        result = self.client.table("sp_pull_checkpoints").select("*").eq(
            "pull_type", self.pull_type
        ).eq(
            "pull_date", self.pull_date.isoformat()
        ).eq(
            "region", self.region
        ).execute()

        return result.data[0] if result.data else None

    def _update_status(self, status: str):
        """Update pull status in database."""
        if not self.pull_id:
            return

        update_data = {
            "status": status,
            "marketplace_status": self.marketplace_status,
            "checkpoint_data": self.checkpoint_data,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "total_row_count": self.total_row_count
        }

        if status == "completed":
            update_data["completed_at"] = datetime.utcnow().isoformat()
            if self.started_at:
                update_data["processing_time_ms"] = int(
                    (datetime.utcnow() - self.started_at).total_seconds() * 1000
                )

        self.client.table("sp_pull_checkpoints").update(
            update_data
        ).eq("id", self.pull_id).execute()

    def start_marketplace(self, marketplace_code: str):
        """Mark marketplace as in progress."""
        self.marketplace_status[marketplace_code] = {
            "status": "in_progress",
            "started_at": datetime.utcnow().isoformat(),
            "retries": self.marketplace_status.get(marketplace_code, {}).get("retries", 0)
        }
        self._update_status("in_progress")
        logger.info(f"Started processing {marketplace_code}")

    def complete_marketplace(self, marketplace_code: str, row_count: int = 0):
        """Mark marketplace as completed."""
        self.marketplace_status[marketplace_code] = {
            "status": "completed",
            "row_count": row_count,
            "completed_at": datetime.utcnow().isoformat()
        }
        self.total_row_count += row_count

        # Update checkpoint
        self.checkpoint_data["last_completed_marketplace"] = marketplace_code

        self._update_status("in_progress")
        logger.info(f"Completed {marketplace_code} with {row_count} rows")

    def fail_marketplace(self, marketplace_code: str, error: str, increment_retry: bool = True):
        """Mark marketplace as failed."""
        current = self.marketplace_status.get(marketplace_code, {})
        retries = current.get("retries", 0)

        if increment_retry:
            retries += 1

        self.marketplace_status[marketplace_code] = {
            "status": "failed",
            "error": error,
            "retries": retries,
            "failed_at": datetime.utcnow().isoformat()
        }
        self.error_count += 1
        self.last_error = f"{marketplace_code}: {error}"

        self._update_status("partial")
        logger.error(f"Failed {marketplace_code} (retry {retries}): {error}")

    def get_incomplete_marketplaces(self, all_marketplaces: List[str]) -> List[str]:
        """
        Get list of marketplaces that need processing.

        Args:
            all_marketplaces: Full list of marketplaces to process

        Returns:
            List of marketplace codes that are not completed
        """
        incomplete = []
        for mp in all_marketplaces:
            status = self.marketplace_status.get(mp, {}).get("status")
            if status != "completed":
                incomplete.append(mp)
        return incomplete

    def save_checkpoint(self, data: dict):
        """Save arbitrary checkpoint data."""
        self.checkpoint_data.update(data)
        self._update_status("in_progress")

    def get_checkpoint(self, key: str = None) -> Any:
        """Get checkpoint data."""
        if key:
            return self.checkpoint_data.get(key)
        return self.checkpoint_data

    def finish_pull(self) -> str:
        """
        Finish pull and determine final status.

        Returns:
            Final status: 'completed', 'partial', or 'failed'
        """
        # Count statuses
        statuses = [mp.get("status") for mp in self.marketplace_status.values()]
        completed_count = statuses.count("completed")
        failed_count = statuses.count("failed")
        total = len(statuses)

        if completed_count == total and total > 0:
            status = "completed"
        elif completed_count > 0:
            status = "partial"
        else:
            status = "failed"

        self._update_status(status)
        logger.info(
            f"Finished pull {self.pull_id}: {status} "
            f"({completed_count}/{total} marketplaces, {self.total_row_count} total rows)"
        )
        return status

    def get_summary(self) -> dict:
        """Get pull summary for reporting."""
        return {
            "pull_id": self.pull_id,
            "pull_type": self.pull_type,
            "pull_date": self.pull_date.isoformat(),
            "region": self.region,
            "marketplace_status": self.marketplace_status,
            "total_row_count": self.total_row_count,
            "error_count": self.error_count,
            "last_error": self.last_error
        }


def get_incomplete_pulls(pull_type: str, region: str = "NA") -> List[dict]:
    """
    Get list of incomplete pulls for a given type.

    Useful for finding pulls that need to be resumed.
    """
    client = get_supabase_client()
    result = client.table("sp_pull_checkpoints").select("*").eq(
        "pull_type", pull_type
    ).eq(
        "region", region
    ).in_(
        "status", ["in_progress", "partial"]
    ).order("pull_date", desc=True).execute()

    return result.data
