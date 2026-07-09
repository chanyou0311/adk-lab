"""oncall (当番) ドメインの mock ツール群 (oncall_data.json バック)。

fixture はモジュールロード時に読み込む (欠落/破損なら import 時に fail-fast)。INC-42/43/44 の
担当は slack #alerts の投稿者と整合する (kenji=INC-42, mio=INC-43, satoshi=INC-44)。
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "oncall_data.json"
_DATA = json.loads(_DATA_PATH.read_text(encoding="utf-8"))  # fail-fast: 欠落/破損で import 時に落とす
_SCHEDULES: list[dict] = _DATA["schedules"]
_SHIFTS: list[dict] = _DATA["shifts"]
_ASSIGNMENTS: dict[str, dict] = {a["incident_id"]: a for a in _DATA["assignments"]}


def make_oncall_tools() -> list:
    """当番ドメインのツール 3 種 (list_schedules / get_shift / list_assignments) を返す。"""

    def oncall_list_schedules() -> dict:
        """List the on-call schedules (rotations)."""
        return {"status": "ok", "schedules": _SCHEDULES}

    def oncall_get_shift(date: str) -> dict:
        """Get who is on-call on a given date (ISO YYYY-MM-DD)."""
        hits = [s for s in _SHIFTS if s["date"] == date]
        if not hits:
            return {"status": "error", "error_message": f"no shift for {date!r}"}
        return {"status": "ok", "date": date, "shifts": hits}

    def oncall_list_assignments(incident_id: str) -> dict:
        """List responder assignments for an incident (e.g. INC-42)."""
        assignment = _ASSIGNMENTS.get(incident_id)
        if assignment is None:
            return {"status": "error", "error_message": f"unknown incident {incident_id!r}",
                    "known": sorted(_ASSIGNMENTS)}
        return {"status": "ok", "assignment": assignment}

    return [oncall_list_schedules, oncall_get_shift, oncall_list_assignments]
