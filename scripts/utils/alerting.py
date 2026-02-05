"""
Alerting Module
Sends notifications for SP-API pull failures and summaries.

Channels:
- Slack webhook (if SLACK_WEBHOOK_URL is configured)
- Console logging (always)
- GitHub Actions annotations (if in CI)
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Handles alerting for SP-API pull events.

    Usage:
        alert = AlertManager()
        alert.alert_failure("sales_traffic", "USA", "429 Too Many Requests")
        alert.send_summary(results)
    """

    def __init__(self):
        self.slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
        self.is_ci = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"

    def _send_slack(self, payload: dict) -> bool:
        """Send message to Slack webhook."""
        if not self.slack_webhook:
            logger.debug("Slack webhook not configured, skipping")
            return False

        try:
            response = requests.post(
                self.slack_webhook,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if response.status_code == 200:
                logger.debug("Slack notification sent")
                return True
            else:
                logger.warning(f"Slack notification failed: {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Slack notification error: {e}")
            return False

    def _github_annotation(self, level: str, message: str):
        """Output GitHub Actions annotation."""
        if self.is_ci:
            # GitHub Actions annotation format
            print(f"::{level}::{message}")

    def alert_failure(
        self,
        pull_type: str,
        marketplace: str,
        error: str,
        retry_count: int = 0
    ):
        """
        Alert when a marketplace pull fails after all retries.

        Args:
            pull_type: Type of pull ('sales_traffic', 'fba_inventory', etc.)
            marketplace: Marketplace code that failed
            error: Error message
            retry_count: Number of retries attempted
        """
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Console logging
        logger.error(
            f"PULL FAILED: {pull_type} - {marketplace} - {error} "
            f"(after {retry_count} retries)"
        )

        # GitHub annotation
        self._github_annotation("error", f"Pull failed: {pull_type}/{marketplace}: {error}")

        # Slack notification
        slack_payload = {
            "attachments": [
                {
                    "color": "#FF0000",  # Red
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "SP-API Pull Failed",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Pull Type:*\n{pull_type}"
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Marketplace:*\n{marketplace}"
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Error:*\n{error}"
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Retries:*\n{retry_count}"
                                }
                            ]
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"Time: {timestamp}"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        self._send_slack(slack_payload)

    def alert_partial_completion(
        self,
        pull_type: str,
        pull_date: str,
        completed: List[str],
        failed: List[str],
        errors: Dict[str, str] = None
    ):
        """
        Alert when a pull completes partially (some marketplaces failed).

        Args:
            pull_type: Type of pull
            pull_date: Date being pulled
            completed: List of completed marketplace codes
            failed: List of failed marketplace codes
            errors: Dict mapping marketplace to error message
        """
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Console logging
        logger.warning(
            f"PARTIAL COMPLETION: {pull_type} for {pull_date} - "
            f"Completed: {completed}, Failed: {failed}"
        )

        # GitHub annotation
        self._github_annotation(
            "warning",
            f"Partial completion: {pull_type} - {len(failed)} marketplace(s) failed"
        )

        # Build error details
        error_text = ""
        if errors:
            error_lines = [f"• {mp}: {err}" for mp, err in errors.items()]
            error_text = "\n".join(error_lines)

        # Slack notification
        slack_payload = {
            "attachments": [
                {
                    "color": "#FFA500",  # Orange
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "SP-API Pull Partial Completion",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Pull Type:*\n{pull_type}"
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Date:*\n{pull_date}"
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Completed:*\n{', '.join(completed) or 'None'}"
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*Failed:*\n{', '.join(failed) or 'None'}"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        if error_text:
            slack_payload["attachments"][0]["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error Details:*\n{error_text}"
                }
            })

        slack_payload["attachments"][0]["blocks"].append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Time: {timestamp}"
                }
            ]
        })

        self._send_slack(slack_payload)

    def send_summary(
        self,
        pull_type: str,
        pull_date: str,
        results: List[Dict],
        total_rows: int = 0,
        duration_seconds: float = 0
    ):
        """
        Send end-of-pull summary.

        Args:
            pull_type: Type of pull
            pull_date: Date pulled
            results: List of marketplace results
            total_rows: Total rows processed
            duration_seconds: Total processing time
        """
        # Count statuses
        completed = [r for r in results if r.get("status") == "completed"]
        failed = [r for r in results if r.get("status") == "failed"]

        all_success = len(failed) == 0 and len(completed) > 0
        status_emoji = "" if all_success else ""
        status_text = "Success" if all_success else f"Partial ({len(failed)} failed)"

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        duration_str = f"{duration_seconds:.1f}s" if duration_seconds else "N/A"

        # Console logging
        logger.info(
            f"PULL SUMMARY: {pull_type} for {pull_date} - {status_text} - "
            f"{len(completed)}/{len(results)} marketplaces, {total_rows} rows, {duration_str}"
        )

        # Only send Slack summary if there were failures or explicitly requested
        if not all_success:
            color = "#00FF00" if all_success else "#FFA500"

            slack_payload = {
                "attachments": [
                    {
                        "color": color,
                        "blocks": [
                            {
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": f"{status_emoji} SP-API Pull {status_text}",
                                    "emoji": True
                                }
                            },
                            {
                                "type": "section",
                                "fields": [
                                    {
                                        "type": "mrkdwn",
                                        "text": f"*Pull Type:*\n{pull_type}"
                                    },
                                    {
                                        "type": "mrkdwn",
                                        "text": f"*Date:*\n{pull_date}"
                                    },
                                    {
                                        "type": "mrkdwn",
                                        "text": f"*Marketplaces:*\n{len(completed)}/{len(results)} success"
                                    },
                                    {
                                        "type": "mrkdwn",
                                        "text": f"*Total Rows:*\n{total_rows:,}"
                                    }
                                ]
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {
                                        "type": "mrkdwn",
                                        "text": f"Duration: {duration_str} | Time: {timestamp}"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }

            self._send_slack(slack_payload)

    def alert_rate_limit(self, api_type: str, wait_time: float, attempt: int):
        """
        Log rate limit event (not sent to Slack to avoid spam).

        Args:
            api_type: API type that hit rate limit
            wait_time: How long we're waiting
            attempt: Retry attempt number
        """
        logger.warning(
            f"RATE LIMITED: {api_type} - waiting {wait_time:.1f}s (attempt {attempt})"
        )

        # GitHub annotation for visibility
        if self.is_ci:
            self._github_annotation(
                "warning",
                f"Rate limited on {api_type}, waiting {wait_time:.1f}s"
            )


# Singleton instance for convenience
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get singleton AlertManager instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


# Convenience functions
def alert_failure(pull_type: str, marketplace: str, error: str, retry_count: int = 0):
    """Send failure alert."""
    get_alert_manager().alert_failure(pull_type, marketplace, error, retry_count)


def alert_partial(pull_type: str, pull_date: str, completed: List[str], failed: List[str], errors: Dict[str, str] = None):
    """Send partial completion alert."""
    get_alert_manager().alert_partial_completion(pull_type, pull_date, completed, failed, errors)


def send_summary(pull_type: str, pull_date: str, results: List[Dict], total_rows: int = 0, duration_seconds: float = 0):
    """Send summary alert."""
    get_alert_manager().send_summary(pull_type, pull_date, results, total_rows, duration_seconds)
