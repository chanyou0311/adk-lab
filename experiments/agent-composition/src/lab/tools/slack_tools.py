"""社内 Slack を模した mock ツール群 (slack_data.json バック)。

docstring は中立的な 1 行のみ (知識は載せない — 本実験の変数はエージェント構成と環境であって
知識配置ではない)。fixture は _fixtures.load_fixture 経由でロードする (欠落/破損は fail-fast)。
"""

from __future__ import annotations

from ._fixtures import load_fixture

_DATA = load_fixture("slack_data")
_MESSAGES: list[dict] = _DATA["messages"]
_CHANNELS: list[str] = _DATA["channels"]


def make_slack_tools() -> list:
    """Slack ツール 3 種 (list_channels / read_channel / search_messages) を返す。"""

    def slack_list_channels() -> dict:
        """List the available Slack channels."""
        return {"status": "ok", "channels": _CHANNELS}

    def slack_read_channel(channel: str, limit: int = 50) -> dict:
        """Read recent messages from a Slack channel (newest first)."""
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
        """Search Slack messages across all channels by substring."""
        q = query.lower()
        hits = [m for m in _MESSAGES if q in m["text"].lower()]
        hits = sorted(hits, key=lambda m: m["ts"], reverse=True)
        return {"status": "ok", "query": query, "match_count": len(hits), "messages": hits}

    return [slack_list_channels, slack_read_channel, slack_search_messages]
