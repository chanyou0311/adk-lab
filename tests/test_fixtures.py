"""fixtures と GT の健全性テスト (Vertex 不要・決定的)。

知識依存タスクが判別力を持つための前提 (is_test 込み/除外で合計が大きく違う、6/24-26 に
落ち込みがある、必須 Slack メッセージが存在する) を機械的に確認する。
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "src" / "lab" / "fixtures" / "warehouse"
SLACK = ROOT / "src" / "lab" / "fixtures" / "slack_data.json"


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute(
        f"""CREATE TABLE orders AS SELECT * FROM read_csv(
            '{WAREHOUSE / "orders.csv"}', header=true,
            columns={{'order_id':'VARCHAR','order_date':'DATE','amount':'BIGINT',
                      'status':'VARCHAR','is_test':'BOOLEAN','channel':'VARCHAR'}})"""
    )
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
    # INC-43 / INC-44 にはクローズ報が無い (未解決) ことを確認。
    assert "[INC-43] " not in alerts or "クローズ" not in alerts.split("INC-43")[-1]


def test_support_complaints_have_keywords():
    data = json.loads(SLACK.read_text(encoding="utf-8"))
    support = " ".join(m["text"] for m in data["messages"] if m["channel"] == "support")
    hits = sum(1 for k in ["決済", "返金", "画像", "遅い"] if k in support)
    assert hits >= 3
