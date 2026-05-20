"""Slack通知 (Webhook経由)。失敗時 / 成功サマリー両対応。"""
from __future__ import annotations

import json
import logging
import os
from urllib import request as urlrequest
from urllib.error import URLError

logger = logging.getLogger(__name__)


def _post_to_webhook(webhook_url: str, payload: dict, timeout: int = 10) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                logger.warning("Slack webhook returned status=%d", resp.status)
    except URLError as e:
        logger.error("Failed to POST to Slack webhook: %s", e)


def notify_failure(error_message: str, context: str = "") -> None:
    """スクレイピング失敗時にSlackへ通知する。"""
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping notification")
        return

    text = ":x: *MUSINSAスクレイピング失敗*"
    if context:
        text += f"\n*Context:* `{context}`"
    text += f"\n```{error_message[:1500]}```"

    _post_to_webhook(webhook, {"text": text})


def notify_success(summary: dict) -> None:
    """成功時にサマリー通知 (任意)。

    summary: {"overall": 200, "brand_weekly": 1800, "brand_monthly": 1800, ...}
    """
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        return

    lines = [":white_check_mark: *MUSINSAスクレイピング完了*"]
    for k, v in summary.items():
        lines.append(f"• `{k}`: {v}件")

    _post_to_webhook(webhook, {"text": "\n".join(lines)})
