"""fixtures と GT の健全性テスト (Vertex 不要・決定的)。

知識依存タスクが判別力を持つための前提 (is_test 込み/除外で合計が大きく違う、6/24-26 に
落ち込みがある、必須 Slack メッセージが存在する) を機械的に確認する。
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from lab.tools.bq_tools import register_warehouse  # DuckDB 登録を bq_tools と 1 本化

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "src" / "lab" / "fixtures" / "warehouse"
SLACK = ROOT / "src" / "lab" / "fixtures" / "slack_data.json"

_PAY = "(subject LIKE '%決済%' OR subject LIKE '%課金%' OR subject LIKE '%返金%')"
_LAT = "EXTRACT(EPOCH FROM (first_response_at - opened_at))"
_THR = f"(CASE WHEN plan='pro' OR {_PAY} THEN 4 ELSE 24 END)*3600"


def _tickets() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    register_warehouse(con, ["support_tickets"])
    return con


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    register_warehouse(con, ["orders"])
    return con


def test_is_test_exclusion_changes_total_materially():
    con = _con()
    with_test = con.execute("SELECT SUM(amount) FROM orders WHERE status='completed'").fetchone()[0]
    without_test = con.execute(
        "SELECT SUM(amount) FROM orders WHERE status='completed' AND is_test=false"
    ).fetchone()[0]
    # 負荷試験注文を除外すると合計が大きく下がる (誤って含めると 1.5 倍以上に膨らむ)。
    assert with_test > without_test * 1.5


def test_load_test_orders_count_is_ten():
    con = _con()
    n = con.execute("SELECT count(*) FROM orders WHERE is_test=true").fetchone()[0]
    assert n == 10


def test_late_june_dip_exists():
    con = _con()
    dip = con.execute(
        "SELECT AVG(d) FROM (SELECT order_date, SUM(amount) d FROM orders "
        "WHERE status='completed' AND is_test=false "
        "AND order_date BETWEEN '2026-06-24' AND '2026-06-26' GROUP BY order_date)"
    ).fetchone()[0]
    normal = con.execute(
        "SELECT AVG(d) FROM (SELECT order_date, SUM(amount) d FROM orders "
        "WHERE status='completed' AND is_test=false "
        "AND order_date < '2026-06-24' GROUP BY order_date)"
    ).fetchone()[0]
    # 6/24-26 の日次売上は平常日の半分未満に落ち込む。
    assert dip < normal * 0.5


def test_cancelled_orders_are_present_and_excluded():
    con = _con()
    cancelled = con.execute("SELECT count(*) FROM orders WHERE status='cancelled'").fetchone()[0]
    assert cancelled > 0  # K3 の判別力のため cancelled が存在する


def test_required_slack_incidents_present():
    data = json.loads(SLACK.read_text(encoding="utf-8"))
    texts = {m["channel"]: [] for m in data["messages"]}
    for m in data["messages"]:
        texts.setdefault(m["channel"], []).append(m["text"])
    alerts = " ".join(texts["alerts"])
    assert "INC-42" in alerts and "クローズ" in alerts  # 解決済み
    assert "INC-43" in alerts  # 未解決 sev1
    assert "INC-44" in alerts  # 未解決 sev2 (内部影響)
    # INC-43 / INC-44 は未解決: それらに言及するメッセージにクローズ報が無いことをメッセージ単位で確認
    # (旧実装の `"[INC-43] " not in alerts or ...` は空白付き文字列が実データに無く恒真だった)。
    close_words = ["クローズ", "解消"]  # 「解決」は「未解決」に部分一致するため使わない
    for inc in ["INC-43", "INC-44"]:
        for m in texts["alerts"]:
            if inc in m:
                assert not any(w in m for w in close_words), f"{inc} にクローズ報がある: {m}"


def test_support_complaints_have_keywords():
    data = json.loads(SLACK.read_text(encoding="utf-8"))
    support = " ".join(m["text"] for m in data["messages"] if m["channel"] == "support")
    hits = sum(1 for k in ["決済", "返金", "画像", "遅い"] if k in support)
    assert hits >= 3


# --- UC3 (support-sla) F1/F2 GT の健全性 ---
def test_uc3_violation_count_in_expected_range():
    con = _tickets()
    n = con.execute(f"SELECT count(*) FROM support_tickets WHERE {_LAT} > {_THR}").fetchone()[0]
    assert 5 <= n <= 8  # F1 の GT が仕様レンジ内


def test_uc3_pro_violations_nonempty():
    con = _tickets()
    ids = [r[0] for r in con.execute(
        f"SELECT ticket_id FROM support_tickets WHERE plan='pro' AND {_LAT} > 4*3600 ORDER BY ticket_id"
    ).fetchall()]
    assert len(ids) >= 1  # F2 の GT (pro 違反 ticket_id) が非空


def test_uc3_payment_override_creates_violation():
    # K8 の判別力: basic かつ支払い関連で 4h<lat<24h のチケットが存在する
    # (K8 を知らないと basic=24h 内として見逃す)。
    con = _tickets()
    n = con.execute(
        f"SELECT count(*) FROM support_tickets WHERE plan!='pro' AND {_PAY} "
        f"AND {_LAT} > 4*3600 AND {_LAT} < 24*3600"
    ).fetchone()[0]
    assert n >= 1


# --------------------------------------------------------------------------- #
# billing / oncall / portal (agent-composition Phase 2a) の健全性
# --------------------------------------------------------------------------- #
BILLING = ROOT / "src" / "lab" / "fixtures" / "billing_data.json"
ONCALL = ROOT / "src" / "lab" / "fixtures" / "oncall_data.json"
PORTAL = ROOT / "src" / "lab" / "fixtures" / "portal_data.json"
_DIP = {"2026-06-24", "2026-06-25", "2026-06-26"}  # INC-42 の決済障害期間


def test_billing_refunds_spike_on_incident_days():
    data = json.loads(BILLING.read_text(encoding="utf-8"))
    refunds = data["refunds"]
    dip = [r for r in refunds if r["date"] in _DIP]
    off = [r for r in refunds if r["date"] not in _DIP]
    # 障害期間 (3 日) に返金の山ができる: 件数・金額とも非障害期間を上回る。
    assert len(dip) >= 12
    assert sum(r["amount"] for r in dip) > sum(r["amount"] for r in off)
    # 障害期間の返金理由は決済/チェックアウトに言及する (INC-42 と整合)。
    assert all(("決済" in r["reason"] or "チェックアウト" in r["reason"]) for r in dip)


def test_billing_charges_reference_invoices_and_refunds_reference_charges():
    data = json.loads(BILLING.read_text(encoding="utf-8"))
    invoice_ids = {inv["invoice_id"] for inv in data["invoices"]}
    charge_ids = {c["charge_id"] for c in data["charges"]}
    # 全 charge の invoice_id が実在する (billing_get_invoice が引ける)。
    assert all(c["invoice_id"] in invoice_ids for c in data["charges"])
    # refund が参照する charge_id が実在する。
    assert all(r["charge_id"] in charge_ids for r in data["refunds"] if r["charge_id"])


def test_oncall_covers_incident_period_and_all_days():
    data = json.loads(ONCALL.read_text(encoding="utf-8"))
    by_id = {a["incident_id"]: a for a in data["assignments"]}
    assert {"INC-42", "INC-43", "INC-44"} <= set(by_id)
    # 担当が slack #alerts 投稿者と整合 (kenji=INC-42, mio=INC-43, satoshi=INC-44)。
    assert any(r["user"] == "kenji" for r in by_id["INC-42"]["responders"])
    assert any(r["user"] == "mio" for r in by_id["INC-43"]["responders"])
    assert any(r["user"] == "satoshi" for r in by_id["INC-44"]["responders"])
    # 全 6 月日 (30 日) に当番が割り当てられている。
    assert len({s["date"] for s in data["shifts"]}) == 30


def test_portal_report_differs_from_correct_revenue():
    # portal_run_report の revenue は test/cancelled 込みの naive 値で、正解 (K1/K3 適用) と異なる。
    # distractor が実際に罠として機能する前提を固定する。
    con = _con()
    correct = con.execute(
        "SELECT SUM(amount) FROM orders WHERE status='completed' AND is_test=false"
    ).fetchone()[0]
    all_amount = con.execute("SELECT SUM(amount) FROM orders").fetchone()[0]
    data = json.loads(PORTAL.read_text(encoding="utf-8"))
    portal_val = data["reports"]["revenue|2026-06"]["value"]
    assert portal_val == all_amount        # naive = 全注文合計 (test/cancelled 込み)
    assert portal_val != correct           # 正解値と異なる = distractor として機能する
    assert portal_val > correct * 1.2      # test 注文の巨額分だけ明確に大きい


def test_portal_catalog_columns_are_stale():
    # portal_describe_dataset("orders") の列は現テーブルと不一致 (is_test/status が無い)。
    data = json.loads(PORTAL.read_text(encoding="utf-8"))
    cols = data["datasets"]["orders"]["columns"]
    assert "is_test" not in cols and "status" not in cols


def test_portal_archive_excludes_incident_period():
    # アーカイブは 30 日より古い (6 月より前) メッセージのみ = 6/24-26 は漏れる。
    data = json.loads(PORTAL.read_text(encoding="utf-8"))
    assert data["archive"]  # 非空 (空で誤魔化していない)
    assert all(m["date"] < "2026-06-01" for m in data["archive"])


# --------------------------------------------------------------------------- #
# billing ツールの日付正規化 + 件数上限 (レビュー fix)
# --------------------------------------------------------------------------- #
def _billing():
    from lab.tools import make_billing_tools
    return make_billing_tools()


def test_billing_accepts_non_zero_padded_dates():
    charges_fn = _billing()[0]
    # 非ゼロ埋め '2026-6-1'..'2026-6-30' でも 6 月全 charge を拾う。
    res = charges_fn("2026-6-1", "2026-6-30")
    assert res["status"] == "ok"
    assert res["count"] == 362  # 6 月の全 charge 件数
    # ゼロ埋め表記と同一結果。
    assert charges_fn("2026-06-01", "2026-06-30")["count"] == 362


def test_billing_invalid_date_returns_error():
    charges_fn = _billing()[0]
    res = charges_fn("2026/06/01", "2026-06-30")  # ISO でない → parse 不能
    assert res["status"] == "error"


def test_billing_caps_sample_to_50():
    charges_fn = _billing()[0]
    res = charges_fn("2026-06-01", "2026-06-30")
    # count は全件 (362) だが返すサンプルは 50 件上限 (コンテキスト圧迫を防ぐ)。
    assert res["count"] == 362
    assert res["returned"] == 50
    assert len(res["charges"]) == 50


def test_oncall_get_shift_accepts_non_zero_padded_date():
    from lab.tools import make_oncall_tools
    get_shift = make_oncall_tools()[1]
    res = get_shift("2026-6-24")  # 非ゼロ埋め
    assert res["status"] == "ok"
    assert res["shifts"]
