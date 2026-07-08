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

from lab.knowledge import DEFAULT_SLA_HOURS, PRO_SLA_HOURS

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
    _thr = f"(CASE WHEN plan='pro' OR {_pay} THEN {PRO_SLA_HOURS} ELSE {DEFAULT_SLA_HOURS} END)*3600"
    sla_violations = con.execute(
        f"SELECT count(*) FROM support_tickets WHERE {_lat} > {_thr}"
    ).fetchone()[0]
    pro_violation_ids = [
        r[0]
        for r in con.execute(
            f"SELECT ticket_id FROM support_tickets WHERE plan='pro' AND {_lat} > {PRO_SLA_HOURS}*3600 "
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
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(億|千万|万|千)?")
_UNIT_MULT = {"億": 1e8, "千万": 1e7, "万": 1e4, "千": 1e3}
# 数値抽出の前に除去するノイズトークン (障害番号・バージョン・severity・年・K規則番号)。
# 年は「2026年」「2026-06-24」「2026/6/24」の形だけ剥がす — 裸の 20\d\d を消すと
# 「2050万円」等の正当な金額まで巻き添えで消え偽陰性になる (レビューで実証)。
_NOISE_RE = re.compile(r"INC-?\d+|v\d+(?:\.\d+)*|sev\d|20\d\d(?=年|[-/月])|K\d+", re.IGNORECASE)


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
        num *= _UNIT_MULT.get(m.group(2), 1)
        vals.append(num)
    return vals


def answer_contains_number(text: str, value: float, rel_tol: float = 0.01) -> bool:
    """テキスト中に value と相対誤差 rel_tol 以内で一致する数値があるか (万/億・カンマ対応)。"""
    if value == 0:
        return any(abs(c) <= rel_tol for c in _extract_numbers(text))
    tol = rel_tol * abs(value)
    return any(abs(c - value) <= tol for c in _extract_numbers(text))


def _has_number(text: str) -> bool:
    """障害番号・バージョン等のノイズを除いた上で何らかの数値を含むか。

    NFKC 正規化を先に行う — 後に回すと全角の年 (２０２６) が ASCII の _NOISE_RE を
    すり抜けてから正規化され、数値として誤カウントされる (レビューで実証)。
    """
    norm = unicodedata.normalize("NFKC", text)
    return len(_extract_numbers(_NOISE_RE.sub(" ", norm))) > 0


def answer_contains_date(text: str, iso: str) -> bool:
    """日付 (ISO "YYYY-MM-DD") を表記ゆらぎ込みで含むか。

    数字境界付きで照合する — 素朴な部分文字列だと "6/3" が "6/30" に一致し、
    別の日付を答えた誤答が pass する (レビューで実証。GT=6/3 に対し売上 2 位は 6/30)。
    """
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
    return any(re.search(rf"(?<!\d){re.escape(f)}(?!\d)", t) for f in forms)


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


# 拒否フレーズを含む文でも、逆接で見積もり/分析へ続くならヘッジであって拒否ではない
# (「算出できませんが、概算では…」「予測する機能はありませんが、データから試算すると…」)。
_HEDGE_CONTRAST_RE = re.compile(r"(ません|ない)(が|けれど|ものの)")
_SENTENCE_SPLIT_RE = re.compile(r"[。\n!?！？]")


def is_refused(text: str) -> bool:
    """capability 拒否か。文単位で判定し、逆接で続くヘッジ文は拒否と数えない。

    旧実装は全文の部分文字列一致だったため「正確には算出できませんが、概算では約800万円」
    のようなヘッジ付きの正答を拒否と誤判定し、C カテゴリと refusal_rate を歪めていた
    (レビューで実証)。限界: 「できません。しかし概算では…」のように文を跨ぐヘッジは
    依然拒否と数える (決定的採点の近似)。
    """
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if any(p in sentence for p in REFUSAL_PATTERNS) and not _HEDGE_CONTRAST_RE.search(sentence):
            return True
    return False


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


# E2 で INC-44 を「顧客影響ではない」と明示的に除外していると認める免罪フレーズ。
# 弱 (内部/社内) は INC-44 と同一文でのみ有効 — 次文まで許すと「社内で対応中です」のような
# 対応主体の記述まで免罪してしまう。強 (影響の明示否定) は直後の文まで有効。
_E2_EXONERATION_WEAK = [
    "内部",
    "社内",
]
_E2_EXONERATION_STRONG = [
    "直接的な影響はありません",
    "顧客への影響はありません",
    "顧客影響はありません",
    "顧客影響なし",
    "顧客影響: なし",
]


_KEN_RE = re.compile(r"(\d+)\s*件")
# 正しい pro 閾値 (K7: PRO_SLA_HOURS 時間) の言及を拾う marker。先頭に数字が付く「24時間」等
# (basic 閾値) を誤検出しないよう否定後読みで境界を付け、「4.0 時間」表記も許容する。
# 閾値は knowledge.py の定数から導出し、K7/K8 本文と採点が常に同じ値に接地するようにする。
_FOUR_HOURS_RE = re.compile(rf"(?<!\d){PRO_SLA_HOURS}(?:\.0+)?\s*時間")
# 「N 時間」表記の有無 (数値時間の言及)。誤閾値への接地を検出するのに使う。
_HOUR_MENTION_RE = re.compile(r"\d+(?:\.\d+)?\s*時間")


def _f1_check(text: str, gt: dict) -> bool:
    """F1: SLA 違反件数を正しく答えているか。

    「違反」に言及する文の中の「N 件」表現から件数を抽出し、GT の違反件数 (6) が含まれる
    ことを要求する。any-number 抽出 (旧実装 v1) だと「6 時間超過」等の無関係な数値を、
    全文の「N 件」抽出 (v2) だと「なお苦情は 6 件」等の別集計を拾って偽陽性になるため、
    違反文にスコープする。違反文に件数が無い場合のみ全文の「N 件」にフォールバックする
    (「該当は 6 件です」のような主語省略の正答を落とさないため)。
    限界: 同一文内に複数の集計が混在するケースは区別しない。
    """
    norm = unicodedata.normalize("NFKC", text)
    violation_counts: set[int] = set()
    all_counts: set[int] = set()
    for sentence in _SENTENCE_SPLIT_RE.split(norm):
        counts = {int(m.group(1)) for m in _KEN_RE.finditer(sentence)}
        all_counts |= counts
        if "違反" in sentence:
            violation_counts |= counts
    effective = violation_counts if violation_counts else all_counts
    return gt["sla_violations"] in effective


def _f2_check(text: str, gt: dict) -> bool:
    """F2: SLA 違反の pro チケット ID を正しく答えているか (方式 b'' — 誤閾値のみ排除)。

    (a) GT の pro 違反 ticket_id が全て含まれ、かつ (b) 誤った閾値に接地していないこと:
    「4 時間」に言及している、または そもそも数値の時間表記 (「N 時間」) が無い、のいずれか。
    F2 の問いは ID を尋ねており閾値の明記は必須でないため、正解 ID を列挙しつつ閾値に触れない
    terse-correct な回答 (知識ありバリアントに多い) は正答として通す。弾くのは「pro=3 時間」等
    の *誤った* 閾値に接地して正解集合をたまたま包含したケース (thin_none に実在) のみ。

    限界: 「レイテンシを時間表記 (例: 約 6.0 時間) しつつ正しい閾値 (4 時間) を明記しない」正答は
    数値時間表記があると見なされ偽陰性になりうる (誤閾値との区別がテキスト上つかないため)。
    支払い override (K8 も 4h) 文脈の「4 時間」も許容する。「24 時間」を 4 時間と誤検出しない。
    """
    if not gt["pro_violation_ids"]:
        return False
    norm = unicodedata.normalize("NFKC", text)
    ids_ok = all(tid in norm for tid in gt["pro_violation_ids"])
    four_hour = _FOUR_HOURS_RE.search(norm) is not None
    has_hour_mention = _HOUR_MENTION_RE.search(norm) is not None
    return ids_ok and (four_hour or not has_hour_mention)


def _e2_check(text: str) -> bool:
    """E2: 顧客影響が出ている未解決障害 = INC-43 のみ、を正しく判別できているか。

    合格 = INC-43 に言及し、かつ INC-44 (sev2・内部影響のみ) を「顧客影響」として
    提示していないこと。後者は決定的近似で判定する: INC-44 に触れていない
    (INC-44 not in text)、または免罪フレーズ (内部 / 社内 / 直接的な影響はありません 等)
    を含み INC-44 を顧客影響から明示的に除外している、のいずれか。

    免罪フレーズは INC-44 に言及する文 (弱+強) とその直後の文 (強のみ) で探す — 全文一致
    (旧実装) だと「INC-43 と INC-44 が顧客影響です。社内で対応中」のように別文脈の「社内」で
    誤 pass する (レビューで実証)。実データの正答は INC-44 と同じ文か直後の文で除外を述べる。

    限界 (LLM judge なしの近似): 窓の外で除外を述べる正答は偽陰性になりうる。解消済み
    INC-42 を未解決として挙げる誤答は検知しない (results_main の実データ 60 件では
    INC-42 言及 18 件が全て解消済みと正しく併記しており、実害ゼロを確認済み)。
    """
    up = text.upper()
    if "INC-43" not in up:
        return False
    if "INC-44" not in up:
        return True
    sentences = _SENTENCE_SPLIT_RE.split(text)
    for i, sentence in enumerate(sentences):
        if "INC-44" in sentence.upper():
            nxt = sentences[i + 1] if i + 1 < len(sentences) else ""
            if any(p in sentence for p in _E2_EXONERATION_WEAK + _E2_EXONERATION_STRONG):
                return True
            if any(p in nxt for p in _E2_EXONERATION_STRONG):
                return True
    return False


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
         lambda t, tc, gt, r: _e2_check(t)),
    # F: UC3 (support-sla)。K7/K8 (plan 別 SLA + 支払い override) を知らないと解けない。
    Task("F1", "F", "初回応答 SLA に違反したサポートチケットは何件ある?", frozenset({"bq"}),
         lambda t, tc, gt, r: _f1_check(t, gt)),
    Task("F2", "F", "SLA 違反チケットのうち pro プランのものの ticket_id を教えて", frozenset({"bq"}),
         lambda t, tc, gt, r: _f2_check(t, gt)),
]

TASKS_BY_ID = {t.id: t for t in TASKS}


def score_record(task: Task | None, final: str, tool_names: list[str],
                 error: str | None = None) -> dict:
    """1 record 分の採点フィールドを計算する — run_eval と rescore の共有実装。

    採点手順 (is_refused → task.check → called_families → route_ok) を 1 箇所に持つことで、
    本番 eval とオフライン再採点が別々の数値を無言で出す乖離を構造的に防ぐ。error record は
    採点せず passed=False / route_ok=None を返す (集計から除外される)。task.check の例外は
    fail 扱いで score_error に記録する。
    """
    refused = is_refused(final)
    passed = False
    score_error = None
    if task is not None and not error:
        try:
            passed = bool(task.check(final, tool_names, GT, refused))
        except Exception as exc:  # noqa: BLE001 - 採点例外は fail 扱い
            score_error = f"{type(exc).__name__}: {exc}"[:200]
    fams = called_families(tool_names)
    route_ok = None
    if task is not None and task.route_scored and not error:
        route_ok = fams == task.expected_families
    out = {
        "passed": passed,
        "refused": refused,
        "families": sorted(fams),
        "expected_families": sorted(task.expected_families) if task else [],
        "route_ok": route_ok,
    }
    if score_error:
        out["score_error"] = score_error
    return out
