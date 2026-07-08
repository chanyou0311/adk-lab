"""社内 Slack を模した mock ツール群 (slack_data.json バック)。

``make_slack_tools(rich)`` の rich フラグで docstring に slack-ops の運用知識を結合できる
(= 知識を tool docstring に配置する tool_desc バリアント用)。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..knowledge import KNOWLEDGE

_DATA_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "slack_data.json"
_DATA = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
_MESSAGES: list[dict] = _DATA["messages"]
_CHANNELS: list[str] = _DATA["channels"]


def make_slack_tools(rich: bool) -> list:
    """Slack ツール 3 種を返す。rich=True なら docstring に KNOWLEDGE["slack-ops"] を結合する。"""

    def slack_list_channels() -> dict:
        return {"status": "ok", "channels": _CHANNELS}

    def slack_read_channel(channel: str, limit: int = 50) -> dict:
        ch = channel.lstrip("#")
        msgs = [m for m in _MESSAGES if m["channel"] == ch]
        if not msgs:
            return {
                "status": "error",
                "error_message": f"unknown channel {channel!r}; use slack_list_channels first",
            }
        msgs = sorted(msgs, key=lambda m: m["ts"], reverse=True)[:limit]
        return {"status": "ok", "channel": ch, "message_count": len(msgs), "messages": msgs}

    def slack_search_messages(query: str) -> dict:
        q = query.lower()
        hits = [m for m in _MESSAGES if q in m["text"].lower()]
        hits = sorted(hits, key=lambda m: m["ts"], reverse=True)
        return {"status": "ok", "query": query, "match_count": len(hits), "messages": hits}

    if rich:
        rules = KNOWLEDGE["slack-ops"]["body"]
        slack_read_channel.__doc__ = (
            "Read recent messages from a Slack channel (newest first).\n\n"
            "Usage rules (どのチャンネルに何があるか・障害の読み方):\n"
            f"{rules}"
        )
        slack_list_channels.__doc__ = (
            "List the team's Slack channels. #alerts=障害 (incident) 通知, #releases=リリース, "
            "#support=顧客の苦情・問い合わせ, #general=雑談."
        )
        slack_search_messages.__doc__ = (
            "Search all Slack channels by substring (case-insensitive). Useful to find an "
            "incident by its [INC-n] tag or a keyword across channels."
        )
    else:
        slack_read_channel.__doc__ = "Read recent messages from a Slack channel (newest first)."
        slack_list_channels.__doc__ = "List the available Slack channels."
        slack_search_messages.__doc__ = "Search Slack messages across all channels by substring."

    return [slack_list_channels, slack_read_channel, slack_search_messages]
