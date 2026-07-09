"""billing (決済) ドメインの mock ツール群 (billing_data.json バック)。

fixture はモジュールロード時に読み込む (欠落/破損なら import 時に fail-fast)。charge は invoice を
1:1 で持ち、refund は charge を参照する。データは既存シナリオ (2026-06、6/24-26 の決済障害 INC-42)
と整合する。
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "billing_data.json"
_DATA = json.loads(_DATA_PATH.read_text(encoding="utf-8"))  # fail-fast: 欠落/破損で import 時に落とす
_CHARGES: list[dict] = _DATA["charges"]
_INVOICES: dict[str, dict] = {inv["invoice_id"]: inv for inv in _DATA["invoices"]}
_REFUNDS: list[dict] = _DATA["refunds"]


def _in_range(iso_date: str, start: str, end: str) -> bool:
    # ISO 日付文字列 (YYYY-MM-DD) は辞書順 = 日付順なので文字列比較で範囲判定できる。
    return start <= iso_date <= end


def make_billing_tools() -> list:
    """決済ドメインのツール 3 種 (list_charges / get_invoice / list_refunds) を返す。"""

    def billing_list_charges(start_date: str, end_date: str) -> dict:
        """List payment charges between start_date and end_date (inclusive, ISO YYYY-MM-DD)."""
        hits = [c for c in _CHARGES if _in_range(c["date"], start_date, end_date)]
        return {"status": "ok", "start_date": start_date, "end_date": end_date,
                "count": len(hits), "charges": hits}

    def billing_get_invoice(invoice_id: str) -> dict:
        """Get the full invoice (line items, total, status) for an invoice_id."""
        inv = _INVOICES.get(invoice_id)
        if inv is None:
            return {"status": "error", "error_message": f"unknown invoice {invoice_id!r}"}
        return {"status": "ok", "invoice": inv}

    def billing_list_refunds(start_date: str, end_date: str) -> dict:
        """List refunds issued between start_date and end_date (inclusive, ISO YYYY-MM-DD)."""
        hits = [r for r in _REFUNDS if _in_range(r["date"], start_date, end_date)]
        return {"status": "ok", "start_date": start_date, "end_date": end_date,
                "count": len(hits), "refunds": hits}

    return [billing_list_charges, billing_get_invoice, billing_list_refunds]
