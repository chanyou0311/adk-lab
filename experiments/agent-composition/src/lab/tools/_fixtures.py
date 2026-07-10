"""fixture JSON のロード定型 (slack/billing/oncall/portal で共有)。

欠落/破損は import 時に例外で fail-fast させる (無内容なツールで eval を静かに交絡させない)。
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    """``src/lab/fixtures/<name>.json`` を読み込んで返す (欠落/破損なら例外で fail-fast)。"""
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
