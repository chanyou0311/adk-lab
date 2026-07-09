"""billing (決済) ドメインの mock ツール群 (billing_data.json バック)。

charge は invoice を 1:1 で持ち、refund は charge を参照する。データは既存シナリオ (2026-06、
6/24-26 の決済障害 INC-42) と整合する。fixture は _fixtures.load_fixture 経由 (欠落/破損は fail-fast)。

list_charges / list_refunds は期間内の全件数 (count) と先頭 50 件のサンプルを返す (6 月 charges は
362 件 ≈ 数十 KB でコンテキストを圧迫するため。bq_query の 200 行上限と同趣旨)。日付引数は date
として parse し、非ゼロ埋め ('2026-6-1') も受理する。parse 不能は status=error で明示返却する。
"""

from __future__ import annotations

import datetime

from ._fixtures import load_fixture

_DATA = load_fixture("billing_data")
_CHARGES: list[dict] = _DATA["charges"]
_INVOICES: dict[str, dict] = {inv["invoice_id"]: inv for inv in _DATA["invoices"]}
_REFUNDS: list[dict] = _DATA["refunds"]

_SAMPLE_CAP = 50  # 期間内が多くてもモデルに返すサンプル件数の上限


def _parse_date(s: str) -> datetime.date | None:
    """ISO 風日付文字列を date に parse する (非ゼロ埋め '2026-6-1' も可)。不能なら None。"""
    try:
        parts = str(s).strip().split("-")
        if len(parts) != 3:
            return None
        y, m, d = (int(p) for p in parts)
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _in_range(rec: dict, start: datetime.date, end: datetime.date) -> bool:
    d = _parse_date(rec["date"])
    return d is not None and start <= d <= end


def _range_query(records: list[dict], key: str, start_date: str, end_date: str) -> dict:
    """期間フィルタ + count + 先頭 _SAMPLE_CAP 件サンプルの共通処理。"""
    ps, pe = _parse_date(start_date), _parse_date(end_date)
    if ps is None or pe is None:
        return {"status": "error",
                "error_message": f"invalid date range {start_date!r}..{end_date!r} (use ISO YYYY-MM-DD)"}
    hits = [rec for rec in records if _in_range(rec, ps, pe)]
    return {"status": "ok", "start_date": start_date, "end_date": end_date,
            "count": len(hits), "returned": min(len(hits), _SAMPLE_CAP), key: hits[:_SAMPLE_CAP]}


def make_billing_tools() -> list:
    """決済ドメインのツール 3 種 (list_charges / get_invoice / list_refunds) を返す。"""

    def billing_list_charges(start_date: str, end_date: str) -> dict:
        """List payment charges between start_date and end_date (inclusive, ISO YYYY-MM-DD).

        Returns the total count in the range and up to 50 sample charges.
        """
        return _range_query(_CHARGES, "charges", start_date, end_date)

    def billing_get_invoice(invoice_id: str) -> dict:
        """Get the full invoice (line items, total, status) for an invoice_id."""
        inv = _INVOICES.get(invoice_id)
        if inv is None:
            return {"status": "error", "error_message": f"unknown invoice {invoice_id!r}"}
        return {"status": "ok", "invoice": inv}

    def billing_list_refunds(start_date: str, end_date: str) -> dict:
        """List refunds issued between start_date and end_date (inclusive, ISO YYYY-MM-DD).

        Returns the total count in the range and up to 50 sample refunds.
        """
        return _range_query(_REFUNDS, "refunds", start_date, end_date)

    return [billing_list_charges, billing_get_invoice, billing_list_refunds]
