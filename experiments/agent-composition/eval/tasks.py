"""タスク定義と決定的な採点ロジック (骨格)。

タスク定義 (TASKS) と ground truth (GT) は本実験のドメイン・タスク設計が固まってから追加する
(後続作業)。scaffold 時点では、実験に依らず再利用できる **汎用の判定ヘルパー** (数値/日付/拒否の
照合、ツール family 判定) と、``Task`` dataclass・``score_record`` の骨格だけを置く。

採点は ``score_record``、集計/レポートは report.py に置き、オフライン再採点 (rescore.py) と
完全に共有する構造を最初から維持する (再現性チェックリスト: 採点器を 1 箇所に集約)。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# ground truth (fixture から採点時に計算する)
# --------------------------------------------------------------------------- #
# タスク設計が固まったら、fixture への DuckDB クエリで GT を計算する _compute_gt() を実装し
# GT = _compute_gt() に差し替える。scaffold ではタスクが無い (TASKS = []) ため空の placeholder。
GT: dict = {}


# --------------------------------------------------------------------------- #
# 数値・日付・拒否の判定ヘルパー (汎用)
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
    別の日付を答えた誤答が pass する (レビューで実証)。
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

    全文の部分文字列一致だと「正確には算出できませんが、概算では約800万円」のような
    ヘッジ付きの正答を拒否と誤判定するため、文単位 + 逆接判定で近似する。限界:
    「できません。しかし概算では…」のように文を跨ぐヘッジは依然拒否と数える。
    """
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if any(p in sentence for p in REFUSAL_PATTERNS) and not _HEDGE_CONTRAST_RE.search(sentence):
            return True
    return False


# --------------------------------------------------------------------------- #
# ツール family 判定 (汎用)
# --------------------------------------------------------------------------- #
# sub-agent 名 → tool family の別名。multi-agent 構成のスペシャリスト名は本実験の設計で
# 確定するため、追加バリアントを作る際にここへ登録する。
_FAMILY_ALIASES: dict[str, str] = {}
_SKILL_TOOLS = {
    "list_skills",
    "load_skill",
    "load_skill_resource",
    "run_skill_script",
    "search_skills",
}


def family_of(name: str) -> str | None:
    """ツール/サブエージェント名を tool family (bq / slack) に写像する (skill 系は無視)。"""
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
# タスク定義 (後続作業で追加)
# --------------------------------------------------------------------------- #
@dataclass
class Task:
    id: str
    category: str
    prompt: str
    expected_families: frozenset[str]
    check: Callable[[str, list[str], dict, bool], bool]
    route_scored: bool = True  # False = family は記録のみで合否に含めない


TASKS: list[Task] = []

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
    scoreable = task is not None and not error
    passed = False
    score_error = None
    if scoreable:
        try:
            passed = bool(task.check(final, tool_names, GT, refused))
        except Exception as exc:  # noqa: BLE001 - 採点例外は fail 扱い
            score_error = f"{type(exc).__name__}: {exc}"[:200]
    fams = called_families(tool_names)
    route_ok = None
    if scoreable and task.route_scored:
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
