"""14 タスクの定義と決定的な採点ロジック。

各タスクは (final_text, tool_names, gt, refused) を受け取り pass/fail を返す。ground truth は
fixture への DuckDB クエリで採点時に計算する (ハードコードしない)。ツール family は呼ばれた
function 名の prefix (bq_ / slack_) と sub-agent 名の別名 (data_analyst→bq, comms_analyst→slack)
から判定し、skill 系ツール (list_skills / load_skill …) は無視する。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb

_WAREHOUSE = Path(__file__).resolve().parent.parent / "src" / "lab" / "fixtures" / "warehouse"


# --------------------------------------------------------------------------- #
# ground truth (fixture から採点時に計算)
# --------------------------------------------------------------------------- #
def _compute_gt() -> dict:
    con = duckdb.connect(":memory:")
    con.execute(
        f"""CREATE TABLE orders AS SELECT * FROM read_csv(
            '{_WAREHOUSE / "orders.csv"}', header=true,
            columns={{'order_id':'VARCHAR','order_date':'DATE','amount':'BIGINT',
                      'status':'VARCHAR','is_test':'BOOLEAN','channel':'VARCHAR'}})"""
    )
    valid = "status='completed' AND is_test=false"
    june_revenue = con.execute(f"SELECT SUM(amount) FROM orders WHERE {valid}").fetchone()[0]
    top_day = con.execute(
        f"SELECT order_date FROM orders WHERE {valid} "
        "GROUP BY order_date ORDER BY SUM(amount) DESC LIMIT 1"
    ).fetchone()[0]
    net_sales = con.execute(f"SELECT SUM(amount)/1.1 FROM orders WHERE {valid}").fetchone()[0]

    # UC3 (support-sla): 初回応答 SLA 違反件数と pro 違反 ticket_id を K7/K8 に従い計算する。
    con.execute(
        f"""CREATE TABLE support_tickets AS SELECT * FROM read_csv(
            '{_WAREHOUSE / "support_tickets.csv"}', header=true, auto_detect=true)"""
    )
    _pay = "(subject LIKE '%決済%' OR subject LIKE '%課金%' OR subject LIKE '%返金%')"
    _lat = "EXTRACT(EPOCH FROM (first_response_at - opened_at))"
    _thr = f"(CASE WHEN plan='pro' OR {_pay} THEN 4 ELSE 24 END)*3600"
    sla_violations = con.execute(
        f"SELECT count(*) FROM support_tickets WHERE {_lat} > {_thr}"
    ).fetchone()[0]
    pro_violation_ids = [
        r[0]
        for r in con.execute(
            f"SELECT ticket_id FROM support_tickets WHERE plan='pro' AND {_lat} > 4*3600 "
            "ORDER BY ticket_id"
        ).fetchall()
    ]
    con.close()
    return {
        "june_revenue": float(june_revenue),
        "top_day": top_day.isoformat(),
        "net_sales": float(net_sales),
        "sla_violations": int(sla_violations),
        "pro_violation_ids": pro_violation_ids,
    }


GT = _compute_gt()


# --------------------------------------------------------------------------- #
# 数値・日付・拒否の判定ヘルパー
# --------------------------------------------------------------------------- #
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(億|万)?")
# 数値抽出の前に除去するノイズトークン (障害番号・バージョン・severity・年・K規則番号)。
_NOISE_RE = re.compile(r"INC-?\d+|v\d+(?:\.\d+)*|sev\d|20\d\d|K[1-6]", re.IGNORECASE)


def _extract_numbers(text: str) -> list[float]:
    text = unicodedata.normalize("NFKC", text)
    vals: list[float] = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        if not raw or raw == ".":
            continue
        try:
            num = float(raw)
        except ValueError:
            continue
        unit = m.group(2)
        if unit == "億":
            num *= 1e8
        elif unit == "万":
            num *= 1e4
        vals.append(num)
    return vals


def answer_contains_number(text: str, value: float, rel_tol: float = 0.01) -> bool:
    """テキスト中に value と相対誤差 rel_tol 以内で一致する数値があるか (万/億・カンマ対応)。"""
    if value == 0:
        return any(abs(c) <= rel_tol for c in _extract_numbers(text))
    tol = rel_tol * abs(value)
    return any(abs(c - value) <= tol for c in _extract_numbers(text))


def _has_number(text: str) -> bool:
    """障害番号・バージョン等のノイズを除いた上で何らかの数値を含むか。"""
    return len(_extract_numbers(_NOISE_RE.sub(" ", text))) > 0


def answer_contains_date(text: str, iso: str) -> bool:
    """日付 (ISO "YYYY-MM-DD") を表記ゆらぎ込みで含むか。"""
    t = unicodedata.normalize("NFKC", text)
    y, m, d = iso.split("-")
    mi, di = int(m), int(d)
    forms = {
        iso,
        f"{y}/{m}/{d}",
        f"{y}年{mi}月{di}日",
        f"{mi}月{di}日",
        f"{mi}/{di}",
        f"{mi:02d}/{di:02d}",
    }
    return any(f in t for f in forms)


# capability を否定する「拒否」フレーズ。ヘッジ付きの見積もり
# (「正確な予測はできませんが概算では…」) を誤検出しないよう、強い能力否定に限定する。
REFUSAL_PATTERNS = [
    "持ち合わせて",
    "機能はありません",
    "機能がありません",
    "機能は提供して",
    "機能は搭載して",
    "予測する機能",
    "分析する機能",
    "予測することはできません",
    "分析することはできません",
    "算出することはできません",
    "することは不可能",
    "算出できません",
    "お答えできません",
    "お役に立てません",
    "私にはできません",
    "I cannot",
    "I'm unable",
    "I am not able",
    "unable to",
]


def is_refused(text: str) -> bool:
    return any(p in text for p in REFUSAL_PATTERNS)


# --------------------------------------------------------------------------- #
# ツール family 判定
# --------------------------------------------------------------------------- #
_FAMILY_ALIASES = {"data_analyst": "bq", "comms_analyst": "slack"}
_SKILL_TOOLS = {
    "list_skills",
    "load_skill",
    "load_skill_resource",
    "run_skill_script",
    "search_skills",
}


def family_of(name: str) -> str | None:
    if name in _SKILL_TOOLS:
        return None
    if name in _FAMILY_ALIASES:
        return _FAMILY_ALIASES[name]
    if name.startswith("bq_"):
        return "bq"
    if name.startswith("slack_"):
        return "slack"
    return None


def called_families(names: list[str]) -> frozenset[str]:
    return frozenset(f for n in names if (f := family_of(n)) is not None)


# --------------------------------------------------------------------------- #
# タスク定義
# --------------------------------------------------------------------------- #
@dataclass
class Task:
    id: str
    category: str
    prompt: str
    expected_families: frozenset[str]
    check: Callable[[str, list[str], dict, bool], bool]
    route_scored: bool = True  # False = family は記録のみで合否に含めない (C3)


def _up(text: str) -> str:
    return text.upper()


_COMPLAINT_KEYWORDS = ["決済", "返金", "画像", "遅い", "アップロード", "課金"]


TASKS: list[Task] = [
    Task("A1", "A", "2026年6月の売上合計を教えて", frozenset({"bq"}),
         lambda t, tc, gt, r: answer_contains_number(t, gt["june_revenue"])),
    Task("A2", "A", "6月で最も売上が大きかった日はいつ?", frozenset({"bq"}),
         lambda t, tc, gt, r: answer_contains_date(t, gt["top_day"])),
    Task("A3", "A", "最近発生した障害について教えて", frozenset({"slack"}),
         lambda t, tc, gt, r: "INC-42" in _up(t) or "INC-43" in _up(t)),
    Task("A4", "A", "6月後半に #support に来ていた苦情を要約して", frozenset({"slack"}),
         lambda t, tc, gt, r: sum(1 for k in _COMPLAINT_KEYWORDS if k in t) >= 2),
    Task("A5", "A", "orders テーブルのカラム構成を教えて", frozenset({"bq"}),
         lambda t, tc, gt, r: sum(
             1 for c in ["order_id", "order_date", "amount", "status", "is_test", "channel"]
             if c in t) >= 4),
    Task("B1", "B", "6月下旬に売上が落ち込んでいないか確認して。落ちていたら原因も調べて",
         frozenset({"bq", "slack"}),
         lambda t, tc, gt, r: (
             any(s in t for s in ["下旬", "6/24", "6/25", "6/26", "6月24", "6月25", "6月26"])
             and ("INC-42" in _up(t) or "チェックアウト" in t or "決済" in t))),
    Task("B2", "B", "INC-42 の障害によるビジネス影響を定量化して", frozenset({"bq", "slack"}),
         lambda t, tc, gt, r: (
             {"bq", "slack"} <= called_families(tc)
             and _has_number(t) and ("売上" in t or "注文" in t))),
    Task("C1", "C", "7月の売上見込みを予測して", frozenset({"bq"}),
         lambda t, tc, gt, r: (
             not r and _has_number(t)
             and any(m in t for m in ["前提", "仮定", "推定", "概算", "見込", "見積"]))),
    Task("C2", "C", "6月の売上トレンドを分析して要点を挙げて", frozenset({"bq"}),
         lambda t, tc, gt, r: (
             not r and any(m in t for m in ["減少", "落ち込", "低下", "下落", "ダウン"]))),
    Task("C3", "C", "もし INC-42 が無かったら6月の売上はどの程度だったと推定できる?",
         frozenset({"bq", "slack"}),
         lambda t, tc, gt, r: not r and _has_number(t), route_scored=False),
    Task("D1", "D", "churn rate とは何ですか?", frozenset(),
         lambda t, tc, gt, r: len(called_families(tc)) == 0 and "解約" in t),
    Task("D2", "D", "SQL の WHERE と HAVING の違いは?", frozenset(),
         lambda t, tc, gt, r: (
             len(called_families(tc)) == 0
             and ("集計" in t or "GROUP BY" in _up(t) or "グループ化" in t))),
    Task("E1", "E", "6月の純売上 (税抜・社内定義) を教えて", frozenset({"bq"}),
         lambda t, tc, gt, r: answer_contains_number(t, gt["net_sales"], rel_tol=0.01)),
    Task("E2", "E", "現在、顧客影響が出ている未解決の障害はある?", frozenset({"slack"}),
         lambda t, tc, gt, r: (
             "INC-43" in _up(t) and ("INC-44" not in _up(t) or "内部" in t))),
    # F: UC3 (support-sla)。K7/K8 (plan 別 SLA + 支払い override) を知らないと解けない。
    Task("F1", "F", "初回応答 SLA に違反したサポートチケットは何件ある?", frozenset({"bq"}),
         lambda t, tc, gt, r: answer_contains_number(t, gt["sla_violations"], rel_tol=0.0)),
    Task("F2", "F", "SLA 違反チケットのうち pro プランのものの ticket_id を教えて", frozenset({"bq"}),
         lambda t, tc, gt, r: (
             bool(gt["pro_violation_ids"])
             and all(tid in t for tid in gt["pro_violation_ids"]))),
]

TASKS_BY_ID = {t.id: t for t in TASKS}
