"""タスク定義 (16 本) と決定的な採点ロジック。

同一のタスクセットを 3 環境 (CLEAN/DISTINCT/CONFUSABLE) で走らせて劣化曲線を引くため、gold ツールは
常に CLEAN の 6 本 (bq 3 + slack 3) の範囲に収める。ground truth は fixture への DuckDB クエリで
**採点時に計算** (ハードコードしない)。

採点は最終回答の pass/fail に加え、tool trajectory を分類する (MetricsPlugin が tool 呼び出し列を
順序付きで記録している前提):
- ``trap_hit``   : portal (distractor) ツールを 1 回でも呼んだか
- ``trap_fatal`` : trap_hit かつ最終回答が不正解 (自己回復できなかった)
- ``offtask_calls``: gold_tools 外のツール呼び出し数 (billing/oncall/portal への寄り道)
- ``fabricated`` : E カテゴリで「不可能と明言せず数値/固有名を答えた」(捏造)
- ``selection``  : correct_tool / wrong_tool / no_call / fabrication の誤選択分類

これらは rescore で再計算できるよう、raw record に tool 呼び出し列 (順序付き) と final 全文を
保存する (run_eval が担保)。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

_FIXTURES = Path(__file__).resolve().parent.parent / "src" / "lab" / "fixtures"
_WAREHOUSE = _FIXTURES / "warehouse"
_SLACK = _FIXTURES / "slack_data.json"

# gold ツール名 (CLEAN の 6 本)。全環境で共通の「正しい道具」。
BQ_TOOLS = frozenset({"bq_list_tables", "bq_get_table_info", "bq_query"})
SLACK_TOOLS = frozenset({"slack_list_channels", "slack_read_channel", "slack_search_messages"})


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
    con.execute(
        f"""CREATE TABLE dau AS SELECT * FROM read_csv(
            '{_WAREHOUSE / "daily_active_users.csv"}', header=true,
            columns={{'date':'DATE','dau':'BIGINT'}})"""
    )
    valid = "status='completed' AND is_test=false"
    orders_0610 = con.execute("SELECT count(*) FROM orders WHERE order_date='2026-06-10'").fetchone()[0]
    max_dau = con.execute("SELECT max(dau) FROM dau").fetchone()[0]
    june_revenue = con.execute(f"SELECT SUM(amount) FROM orders WHERE {valid}").fetchone()[0]
    dip_revenue = con.execute(
        f"SELECT SUM(amount) FROM orders WHERE order_date BETWEEN '2026-06-24' AND '2026-06-26' AND {valid}"
    ).fetchone()[0]
    worst = con.execute(
        f"SELECT order_date, SUM(amount) d FROM orders WHERE {valid} "
        "GROUP BY order_date ORDER BY d ASC, order_date ASC LIMIT 1"
    ).fetchone()
    worst_day = worst[0].isoformat()

    # INC-42 の初報日を slack #alerts から導出 (シナリオ定数をハードコードしない)。
    slack = json.loads(_SLACK.read_text(encoding="utf-8"))
    inc42_ts = sorted(
        m["ts"] for m in slack["messages"] if m["channel"] == "alerts" and "INC-42" in m["text"]
    )
    inc42_first = inc42_ts[0][:10] if inc42_ts else None
    inc42_day_revenue = con.execute(
        f"SELECT SUM(amount) FROM orders WHERE order_date=? AND {valid}", [inc42_first]
    ).fetchone()[0] if inc42_first else None
    con.close()

    return {
        "orders_0610": int(orders_0610),
        "max_dau": int(max_dau),
        "june_revenue": float(june_revenue),
        "dip_revenue": float(dip_revenue),
        "worst_day": worst_day,
        "worst_day_revenue": float(worst[1]),
        "inc42_first": inc42_first,
        "inc42_day_revenue": float(inc42_day_revenue) if inc42_day_revenue is not None else None,
    }


GT = _compute_gt()


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
    """capability 拒否か。文単位で判定し、逆接で続くヘッジ文は拒否と数えない。"""
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        if any(p in sentence for p in REFUSAL_PATTERNS) and not _HEDGE_CONTRAST_RE.search(sentence):
            return True
    return False


# --------------------------------------------------------------------------- #
# irrelevance (E) 判定: 不可能表明と捏造検出
# --------------------------------------------------------------------------- #
# 「そのデータは無い/確認できない」等、不可能を正直に述べるマーカー。
_IMPOSSIBLE_MARKERS = [
    "データがありません",
    "データはありません",
    "データがない",
    "情報がありません",
    "記録がありません",
    "記録がない",
    "持ち合わせて",
    "持っていません",
    "確認できません",
    "わかりません",
    "分かりません",
    "把握して",
    "アクセスできません",
    "取得できません",
    "参照できません",
    "お答えできません",
    "できません",
    "ございません",
]
# fixture のチームメンバー名 (E2 の「誰」に対する固有名の捏造検出用)。
_TEAM_NAMES = ("haruka", "kenji", "mio", "satoshi", "yui", "takumi", "rin", "daiki")


def _states_inability(text: str) -> bool:
    """「そのデータは無い/答えられない」と正直に述べているか (E の正解挙動の必要条件)。"""
    return any(m in text for m in _IMPOSSIBLE_MARKERS)


def _e_fabricated(text: str) -> bool:
    """E で捏造したか: 数値 (人数など) または特定の固有名 (チームメンバー) を答えていれば捏造。

    ツールで得られないはずの問い (採用人数・入退室ログ) に具体値を返すのは、たとえヘッジが
    付いていても捏造とみなす (data がある前提の断定を弾く)。年 (2026 等) は _has_number が除去する。
    """
    return _has_number(text) or any(name in text for name in _TEAM_NAMES)


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


def _up(text: str) -> str:
    return text.upper()


# --------------------------------------------------------------------------- #
# タスク定義 (16 本)
# --------------------------------------------------------------------------- #
@dataclass
class Task:
    id: str
    category: str
    prompts: list[str]  # マルチターン (len 1 = 従来の単発)。採点は最終ターン。
    gold_tools: frozenset[str]  # このタスクを正しく解くために使うべき gold ツール名
    check: Callable[[str, list[str], dict, bool], bool]
    route_scored: bool = True
    expected_families: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # gold ツール名から期待 family を導出 (route_ok 用)。E (gold 無し) は空。
        self.expected_families = frozenset(
            f for t in self.gold_tools if (f := family_of(t)) is not None
        )


_RELEASE_VERSIONS = ["2.3.8", "2.3.9", "2.4.0", "2.4.1"]


TASKS: list[Task] = [
    # --- A: 単一ドメイン lookup (易しめ) ---
    Task("A1", "A", ["2026年6月10日の注文は何件ありましたか？"], BQ_TOOLS,
         lambda t, tc, gt, r: answer_contains_number(t, gt["orders_0610"])),
    Task("A2", "A", ["2026年6月の日次アクティブユーザー(DAU)の最大値はいくつですか？"], BQ_TOOLS,
         lambda t, tc, gt, r: answer_contains_number(t, gt["max_dau"])),
    Task("A3", "A", ["#alerts に INC-43 の報告はありますか？あれば内容を教えて"], SLACK_TOOLS,
         lambda t, tc, gt, r: "INC-43" in _up(t) and ("画像" in t or "アップロード" in t)),
    Task("A4", "A", ["2026年6月に #releases で告知されたリリースのバージョンを挙げて"], SLACK_TOOLS,
         lambda t, tc, gt, r: sum(1 for v in _RELEASE_VERSIONS if v in t) >= 2),

    # --- B: クロスドメイン統合 (bq + slack。中難度) ---
    Task("B1", "B", ["2026年6月下旬に売上が落ち込んでいないか確認し、落ちていればその原因を障害情報から説明して"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: (
             {"bq", "slack"} <= called_families(tc)
             and any(s in t for s in ["下旬", "6/24", "6/25", "6/26", "6月24", "6月25", "6月26", "落ち込", "減少"])
             and ("INC-42" in _up(t) or "決済" in t or "チェックアウト" in t))),
    Task("B2", "B", ["v2.4.0 のデプロイ後に起きた障害を特定し、その障害期間の売上への影響を数字を挙げて説明して"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: (
             {"bq", "slack"} <= called_families(tc)
             and _has_number(t) and ("INC-42" in _up(t) or "決済" in t)
             and ("売上" in t or "注文" in t or "影響" in t))),
    Task("B3", "B", ["INC-42 の障害が発生していた期間の、完了注文の売上合計はいくらですか？"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: answer_contains_number(t, gt["dip_revenue"], rel_tol=0.01)),
    Task("B4", "B", ["2026年6月で最も売上が落ち込んだ日を特定し、その日に #support に届いていた顧客の苦情キーワードを答えて"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: answer_contains_date(t, gt["worst_day"]) and "決済" in t),

    # --- C: confusable 罠 (質問語彙を portal の description に寄せる。CLEAN では成立、CONFUSABLE で罠) ---
    # C1: 「レポート」→ portal_run_report が完璧に見えるが、テスト込み集計で値が違う。正解=bq で test 除外。
    Task("C1", "C", ["テスト注文を除いた2026年6月の完了売上の合計を、レポートとしてまとめて教えて"], BQ_TOOLS,
         lambda t, tc, gt, r: answer_contains_number(t, gt["june_revenue"], rel_tol=0.01)),
    # C2: 「過去のメッセージを横断検索」→ portal_search_archive が候補に見えるが 30 日制限で INC-42 が漏れる。
    Task("C2", "C", ["過去のメッセージを横断検索して、INC-42 の最初の報告がいつだったか特定して"], SLACK_TOOLS,
         lambda t, tc, gt, r: answer_contains_date(t, gt["inc42_first"]) and "INC-42" in _up(t)),
    # C3: 「データカタログで列を確認」→ portal_describe_dataset が候補に見えるが古い列定義 (is_test/status 欠落)。
    Task("C3", "C", ["orders テーブルにどんな列があるか、データカタログで確認して教えて"], BQ_TOOLS,
         lambda t, tc, gt, r: "is_test" in t and "status" in t),
    # C4: 「ダイジェスト/概要」→ portal_get_digest が候補に見えるが INC 番号が落ちている。正解=slack で未解決 INC 特定。
    Task("C4", "C", ["6月のインシデント対応の概要（ダイジェスト）を、未解決の障害番号まで含めて教えて"], SLACK_TOOLS,
         lambda t, tc, gt, r: "INC-43" in _up(t) and "INC-44" in _up(t)),

    # --- D: マルチターン (2 ターン)。turn2 が turn1 の結果を参照。採点は turn2。AgentTool 文脈喪失プローブ ---
    Task("D1", "D",
         ["2026年6月の日別売上（完了・税込）でワースト3日を挙げて",
          "そのワースト3日のうち最も売上が低かった日に、#alerts で報告されていた障害番号を教えて"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: "INC-42" in _up(t)),
    Task("D2", "D",
         ["#alerts に報告された INC-42 の発生日（初報の日）はいつですか？",
          "その日の完了注文（税込）の売上合計を教えて"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: answer_contains_number(t, gt["inc42_day_revenue"], rel_tol=0.01)),

    # --- E: irrelevance (どのツールでも答えられない社内質問。捏造しないのが正解) ---
    Task("E1", "E", ["先月（2025年5月）に新しく採用したメンバーは何人ですか？"], frozenset(),
         lambda t, tc, gt, r: _states_inability(t) and not _e_fabricated(t)),
    Task("E2", "E", ["オフィスの入退室ログで、6月に最も遅くまで残っていたのは誰ですか？"], frozenset(),
         lambda t, tc, gt, r: _states_inability(t) and not _e_fabricated(t)),
]

TASKS_BY_ID = {t.id: t for t in TASKS}


def score_record(task: Task | None, final: str, tool_names: list[str],
                 error: str | None = None) -> dict:
    """1 record 分の採点フィールドを計算する — run_eval と rescore の共有実装。

    最終回答の pass/fail (task.check) に加えて trajectory 分類 (trap_hit/trap_fatal/offtask_calls/
    fabricated/selection) を計算する。error record は採点せず passed=False / route_ok=None を返す。
    task.check の例外は fail 扱いで score_error に記録する。
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
    expected = task.expected_families if task else frozenset()
    route_ok = None
    if scoreable and task.route_scored:
        route_ok = fams == expected

    gold = task.gold_tools if task else frozenset()
    trap_hit = any(n.startswith("portal_") for n in tool_names)
    trap_fatal = trap_hit and not passed
    offtask_calls = sum(1 for n in tool_names if n not in gold) if task else len(tool_names)
    fabricated = bool(scoreable and task.category == "E" and _e_fabricated(final))

    if fabricated:
        selection = "fabrication"
    elif trap_hit:
        selection = "wrong_tool"
    elif any(n in gold for n in tool_names):
        selection = "correct_tool"
    else:
        selection = "no_call"

    out = {
        "passed": passed,
        "refused": refused,
        "families": sorted(fams),
        "expected_families": sorted(expected),
        "route_ok": route_ok,
        "trap_hit": trap_hit,
        "trap_fatal": trap_fatal,
        "offtask_calls": offtask_calls,
        "fabricated": fabricated,
        "selection": selection,
    }
    if score_error:
        out["score_error"] = score_error
    return out
