"""Slack alerts via bot token + channel ID (chat.postMessage).

Falls back to stdout when SLACK_BOT_TOKEN / SLACK_CHANNEL_ID are not set.
"""

import os
import sys

import requests


def post(text, token=None, channel=None):
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    channel = channel or os.environ.get("SLACK_CHANNEL_ID")
    if not (token and channel):
        print(text)
        print("[slack] SLACK_BOT_TOKEN / SLACK_CHANNEL_ID not set - printed instead",
              file=sys.stderr)
        return False
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "text": text},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        err = data.get("error", "unknown")
        hint = ""
        if err == "not_in_channel":
            hint = " -> invite the bot to the channel: /invite @YourBotName"
        elif err in ("invalid_auth", "account_inactive"):
            hint = " -> check SLACK_BOT_TOKEN secret"
        elif err == "channel_not_found":
            hint = " -> check SLACK_CHANNEL_ID secret (use the channel ID, e.g. C0123..., not the name)"
        raise RuntimeError(f"Slack API error: {err}{hint}")
    return True
