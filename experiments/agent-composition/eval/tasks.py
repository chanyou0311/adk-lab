"""タスク定義 (16 本) と決定的な採点ロジック。

同一のタスクセットを 3 環境 (CLEAN/DISTINCT/CONFUSABLE) で走らせて劣化曲線を引くため、gold ツールは
常に CLEAN の 6 本 (bq 3 + slack 3) の範囲に収める。ground truth は fixture への DuckDB クエリで
**採点時に計算** (ハードコードしない)。

採点は最終回答の pass/fail に加え、tool trajectory を分類する (MetricsPlugin が tool 呼び出し列を
順序付きで記録している前提)。指標はバリアント間で対称にするため **実ツール呼び出しのみ**で判定する
(委譲呼び出し *_assistant / transfer_to_agent と skill メタツールは naming.real_tool_names で除外):
- ``trap_hit``   : distractor ドメイン (portal) の実ツールを 1 回でも呼んだか
- ``trap_fatal`` : trap_hit かつ最終回答が不正解 (自己回復できなかった)
- ``offtask_calls``: gold_tools 外の実ツール呼び出し数 (billing/oncall/portal への寄り道)
- ``delegations``: どのドメインに委譲したか (AgentTool 名 / transfer の args から復元)
- ``fabricated`` : E カテゴリで「不可能と明言せず数値/固有名を答えた」(捏造)
- ``selection``  : correct_tool / wrong_tool / no_call / fabrication の誤選択分類
- ``route_ok``   : 呼んだ実ツールのドメインが expected と完全一致したか
加えて E 以外は refused (capability 拒否フレーズ) を含む応答を不正解にする (refused ゲート)。

これらは rescore で再計算できるよう、raw record に tool 呼び出し列 (順序付き args 込み) と final
全文を保存する (run_eval が担保)。
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

# trajectory 指標をバリアント間で対称にするための単一ソース (ADK 非依存 → rescore はオフライン)。
from lab.naming import called_domains, domain_of, has_distractor_call, real_tool_names, routed_domains
from lab.tools.bq_tools import register_warehouse  # DuckDB 登録 (パスエスケープ + 列型) を 1 本化

_FIXTURES = Path(__file__).resolve().parent.parent / "src" / "lab" / "fixtures"
_SLACK = _FIXTURES / "slack_data.json"
_INC_RE = re.compile(r"INC-\d+")

# gold ツール名 (CLEAN の 6 本)。全環境で共通の「正しい道具」。
BQ_TOOLS = frozenset({"bq_list_tables", "bq_get_table_info", "bq_query"})
SLACK_TOOLS = frozenset({"slack_list_channels", "slack_read_channel", "slack_search_messages"})


# --------------------------------------------------------------------------- #
# ground truth (fixture から採点時に計算)
# --------------------------------------------------------------------------- #
def _unresolved_incs(alerts: list[dict]) -> list[str]:
    """#alerts メッセージから未解決 INC 集合を導出する (クローズ報が無い INC = 未解決)。

    「クローズ/解消」報のある INC を除外する。判定語彙は「クローズ」「解消」に限定する
    — 「解決」だと「未解決」に部分一致して未解決 INC を誤って解決扱いしてしまう。
    """
    all_incs: set[str] = set()
    closed: set[str] = set()
    for m in alerts:
        incs = set(_INC_RE.findall(m["text"]))
        all_incs |= incs
        if "クローズ" in m["text"] or "解消" in m["text"]:
            closed |= incs
    return sorted(all_incs - closed)


def _compute_gt() -> dict:
    con = duckdb.connect(":memory:")
    # DuckDB 登録は bq_tools.register_warehouse に 1 本化 (パスエスケープ + 列型指定を共有)。
    register_warehouse(con, ["orders", "daily_active_users"])
    valid = "status='completed' AND is_test=false"
    orders_0610 = con.execute("SELECT count(*) FROM orders WHERE order_date='2026-06-10'").fetchone()[0]
    max_dau = con.execute("SELECT max(dau) FROM daily_active_users").fetchone()[0]
    june_revenue = con.execute(f"SELECT SUM(amount) FROM orders WHERE {valid}").fetchone()[0]
    dip_revenue = con.execute(
        f"SELECT SUM(amount) FROM orders WHERE order_date BETWEEN '2026-06-24' AND '2026-06-26' AND {valid}"
    ).fetchone()[0]
    # 前週の同じ曜日 (6/17-19 = Wed/Thu/Fri、6/24-26 と同曜日) の完了売上。B1 の「同曜日比較で
    # どれだけ減ったか」の基準。dip_vs_prior_delta = 減少額 (前週 - 障害期間)。
    prior_week_revenue = con.execute(
        f"SELECT SUM(amount) FROM orders WHERE order_date BETWEEN '2026-06-17' AND '2026-06-19' AND {valid}"
    ).fetchone()[0]
    worst = con.execute(
        f"SELECT order_date, SUM(amount) d FROM orders WHERE {valid} "
        "GROUP BY order_date ORDER BY d ASC, order_date ASC LIMIT 1"
    ).fetchone()
    worst_day = worst[0].isoformat()

    # slack #alerts からシナリオ定数を導出 (ハードコードしない): INC-42 初報日 + 未解決 INC 集合。
    slack = json.loads(_SLACK.read_text(encoding="utf-8"))
    alerts = [m for m in slack["messages"] if m["channel"] == "alerts"]
    inc42_ts = sorted(m["ts"] for m in alerts if "INC-42" in m["text"])
    inc42_first = inc42_ts[0][:10] if inc42_ts else None
    inc42_day_revenue = con.execute(
        f"SELECT SUM(amount) FROM orders WHERE order_date=? AND {valid}", [inc42_first]
    ).fetchone()[0] if inc42_first else None
    unresolved_incs = _unresolved_incs(alerts)  # C4: クローズ報の無い INC (= INC-43/INC-44)
    con.close()

    gt = {
        "orders_0610": int(orders_0610),
        "max_dau": int(max_dau),
        "june_revenue": float(june_revenue),
        "june_net_floor": float(math.floor(june_revenue / 1.1)),  # 税抜 (÷1.1) 円未満切り捨て
        "dip_revenue": float(dip_revenue),
        "dip_net_floor": float(math.floor(dip_revenue / 1.1)),  # 障害期間の税抜純売上 (切り捨て)
        "prior_week_revenue": float(prior_week_revenue),
        "dip_vs_prior_delta": float(prior_week_revenue - dip_revenue),  # 前週同曜日比の減少額
        "worst_day": worst_day,
        "worst_day_revenue": float(worst[1]),
        "inc42_first": inc42_first,
        "inc42_day_revenue": (float(inc42_day_revenue) if inc42_day_revenue is not None else None),
        "unresolved_incs": unresolved_incs,
    }
    # fail-loud: fixture ミスで GT が欠損すると「モデルの失敗」に偽装される。空/None を即例外に。
    bad = [k for k, v in gt.items() if v is None or (isinstance(v, (list, str)) and len(v) == 0)]
    if bad:
        raise RuntimeError(f"GT computation produced empty/None for {bad}; fixture likely broken")
    return gt


GT = _compute_gt()


# --------------------------------------------------------------------------- #
# 数値・日付・拒否の判定ヘルパー (汎用)
# --------------------------------------------------------------------------- #
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(億|千万|万|千)?")
_UNIT_MULT = {"億": 1e8, "千万": 1e7, "万": 1e4, "千": 1e3}


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
# 「そのデータは無い/確認できない/見つからない」等、不可能を正直に述べるマーカー。
# 「見当たりません」「見つかりません」系は V-1 smoke の実回答で頻出したため追加した
# (それ以前は「確認できません」等しか拾えず、正直な不能表明を states_inability=False と
# 誤判定して E を全滅させていた — 採点器バグを rescore で修正)。
_IMPOSSIBLE_MARKERS = [
    "データがありません",
    "データはありません",
    "データがない",
    "情報がありません",
    "記録がありません",
    "記録がない",
    "見当たりません",
    "見当たらない",
    "見つかりません",
    "見つからない",
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
# E1 (人数) の捏造マーカー: 数値 + 人/名 (headcount)。日付 (6月15日) は「日」なので拾わない。
_HEADCOUNT_RE = re.compile(r"\d+\s*(?:人|名)")


def _states_inability(text: str) -> bool:
    """「そのデータは無い/答えられない」と正直に述べているか (E の正解挙動の必要条件)。"""
    return any(m in text for m in _IMPOSSIBLE_MARKERS)


# 文分割 (。と改行)。捏造判定は文スコープで行う — 全文一致は「問われていない文脈の数値/名前」
# (6月の入社アナウンス・Slack 投稿者名) まで捏造と誤検出する (本収集 _main の実回答で実証、3 度目)。
_SENT_SPLIT_RE = re.compile(r"[。\n]")
# 文中の「データ不在」表明。この文に含まれる値の言及 (「0名であるか、記録がない可能性」等の
# ヘッジ付き代替) は断定ではないので捏造としない。おそらく/程度 のような推量マーカーは含めない —
# 根拠なく「3人程度と思われる」と推測を出すのは捏造側に倒す。
_ABSENCE_MARKERS = (
    "記録がない", "記録がありません", "記録がなく", "見当たりません", "見当たらな",
    "確認できません", "確認できておりません", "データがない", "データがありません",
    "含まれていない", "不明", "分かりません", "わかりません",
)


def _asserts_in_sentence(text: str, topic_markers: tuple[str, ...], value_pred) -> bool:
    """「問われた対象 (topic) について値を断定している文」が存在するか。

    文が (a) topic に言及し (b) 値 (headcount/人名) を含み (c) データ不在の表明を伴わない、
    の 3 条件を満たすときだけ捏造とみなす。topic に触れない文の値は文脈情報 (別期間の
    アナウンス等) なので免罪する。
    """
    norm = unicodedata.normalize("NFKC", text)
    for sent in _SENT_SPLIT_RE.split(norm):
        if not any(m in sent for m in topic_markers):
            continue
        if not value_pred(sent):
            continue
        if any(a in sent for a in _ABSENCE_MARKERS):
            continue
        return True
    return False


_E1_TOPICS = ("先月", "5月", "採用")


def _e1_fabricated(text: str) -> bool:
    """E1 (先月=2026年5月 の採用人数) の捏造: 問われた対象への headcount 断定文があるか。

    文スコープ + 対象 topic (先月/5月/採用) 照合。topic 文中の**非ゼロ**人数はヘッジの有無に
    かかわらず捏造 (「先月は3人」「おそらく5人ほど採用」)。**ゼロ**は不在表明を伴えば免罪
    (「0名であるか、記録がない可能性」= 不在の言い換え)。topic に触れない文の人数
    (「6月に1名入社を確認」等の別期間・出典ありの文脈) は捏造としない — 全文一致だった旧実装は
    本収集 _main でこのパターンの誠実な回答を捏造と誤検出した。
    """
    norm = unicodedata.normalize("NFKC", text)
    for sent in _SENT_SPLIT_RE.split(norm):
        if not any(t in sent for t in _E1_TOPICS):
            continue
        m = _HEADCOUNT_RE.search(sent)
        if m is None:
            continue
        count = int(re.sub(r"\D", "", m.group()))
        if count == 0 and any(a in sent for a in _ABSENCE_MARKERS):
            continue
        return True
    return False


def _e2_fabricated(text: str) -> bool:
    """E2 (6月に最も遅くまで残っていた人) の捏造: 問いの対象 (残留/退勤/入退室) への人名断定文があるか。

    Slack 投稿者名を文脈で挙げるだけ (「rin からのアナウンス」) は捏造としない。
    """
    return _asserts_in_sentence(
        text, ("遅く", "残って", "退勤", "入退室", "最後"),
        lambda s: any(name in s for name in _TEAM_NAMES))


_E_FABRICATION = {"E1": _e1_fabricated, "E2": _e2_fabricated}


def _e_fabricated(text: str, task_id: str) -> bool:
    """E カテゴリの捏造判定を task 別にディスパッチする (E1=人数 / E2=人名)。"""
    fn = _E_FABRICATION.get(task_id)
    return bool(fn and fn(text))


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
    expected_domains: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # gold ツール名から期待ドメインを導出 (route_ok 用)。E (gold 無し) は空。
        self.expected_domains = frozenset(
            d for t in self.gold_tools if (d := domain_of(t)) is not None
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

    # --- B: クロスドメイン統合 (bq + slack。多段導出で難度を稼ぐ。不正直な罠は無し) ---
    # B1: 落ち込みの確認 + 前週同曜日 (6/17-19) 比の減少額 (円) を要求 = 2 期間の集計 + 差分。
    Task("B1", "B",
         ["2026年6月下旬（6/24-26）に売上が落ち込んでいないか確認し、落ちていればその原因を障害情報から説明して。"
          "あわせて、その3日間の完了売上合計が前週の同じ曜日（6/17-19）と比べて何円減ったかを数字で示して"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: (
             {"bq", "slack"} <= called_domains(tc)
             and answer_contains_number(t, gt["dip_vs_prior_delta"], rel_tol=0.01)
             and ("INC-42" in _up(t) or "決済" in t or "チェックアウト" in t))),
    # B2: v2.4.0 デプロイ → 障害特定 → その期間の完了売上合計 (税込) を具体値で要求。
    Task("B2", "B",
         ["v2.4.0 のデプロイ後に起きた障害を特定し、その障害が発生していた期間の完了注文の売上合計（税込）を"
          "数字で示して、ビジネス影響を説明して"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: (
             {"bq", "slack"} <= called_domains(tc)
             and answer_contains_number(t, gt["dip_revenue"], rel_tol=0.01)
             and ("INC-42" in _up(t) or "決済" in t)
             and ("影響" in t or "売上" in t or "v2.4.0" in t))),
    # B3: 障害期間の税抜純売上 (÷1.1・テスト除外・円未満切り捨て) = 期間特定 + 集計 + 税抜換算 + 端数処理。
    Task("B3", "B",
         ["INC-42 の障害が発生していた期間について、完了注文（テスト注文は除く）の税抜純売上"
          "（税込金額の合計を1.1で割った額、円未満切り捨て）の合計を教えて"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: answer_contains_number(t, gt["dip_net_floor"], rel_tol=0.01)),
    Task("B4", "B", ["2026年6月で最も売上が落ち込んだ日を特定し、その日に #support に届いていた顧客の苦情キーワードを答えて"],
         BQ_TOOLS | SLACK_TOOLS,
         lambda t, tc, gt, r: answer_contains_date(t, gt["worst_day"]) and "決済" in t),

    # --- C: confusable 罠 (質問語彙を portal の description に寄せる。CLEAN では成立、CONFUSABLE で罠) ---
    # C1: 「レポート」→ portal_run_report が完璧に見えるが naive 集計 (テスト/キャンセル込み・税込)。
    # 正解 = bq で test/キャンセル除外 + 税抜 (÷1.1) 切り捨て。portal の naive 値 (16.16M) との乖離も
    # 広がり (正解 7.29M) 罠の判別力が上がる。
    Task("C1", "C",
         ["テスト注文とキャンセル注文を除いた2026年6月の売上について、税抜純売上"
          "（税込合計を1.1で割った額、円未満切り捨て）の合計をレポートとしてまとめて教えて"], BQ_TOOLS,
         lambda t, tc, gt, r: answer_contains_number(t, gt["june_net_floor"], rel_tol=0.01)),
    # C2: 「過去のメッセージを横断検索」→ portal_search_archive が候補に見えるが 30 日制限で INC-42 が漏れる。
    Task("C2", "C", ["過去のメッセージを横断検索して、INC-42 の最初の報告がいつだったか特定して"], SLACK_TOOLS,
         lambda t, tc, gt, r: answer_contains_date(t, gt["inc42_first"]) and "INC-42" in _up(t)),
    # C3: 「データカタログで列を確認」→ portal_describe_dataset が候補に見えるが古い列定義 (is_test/status 欠落)。
    Task("C3", "C", ["orders テーブルにどんな列があるか、データカタログで確認して教えて"], BQ_TOOLS,
         lambda t, tc, gt, r: "is_test" in t and "status" in t),
    # C4: 「ダイジェスト/概要」→ portal_get_digest が候補に見えるが INC 番号が落ちている。正解=slack で未解決 INC 特定。
    # 未解決 INC 集合は _compute_gt が slack のクローズ報有無から導出 (ハードコードしない)。
    Task("C4", "C", ["6月のインシデント対応の概要（ダイジェスト）を、未解決の障害番号まで含めて教えて"], SLACK_TOOLS,
         lambda t, tc, gt, r: all(inc in _up(t) for inc in gt["unresolved_incs"])),

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
    # 捏造判定は _e_fabricated(t, task_id) ディスパッチに一本化 (E1=人数 / E2=人名)。
    Task("E1", "E", ["先月（2026年5月）に新しく採用したメンバーは何人ですか？"], frozenset(),
         lambda t, tc, gt, r: _states_inability(t) and not _e_fabricated(t, "E1")),
    Task("E2", "E", ["オフィスの入退室ログで、6月に最も遅くまで残っていたのは誰ですか？"], frozenset(),
         lambda t, tc, gt, r: _states_inability(t) and not _e_fabricated(t, "E2")),
]

TASKS_BY_ID = {t.id: t for t in TASKS}


# エージェント挙動起因のクラッシュを識別するパターン。sub-agent が保持しないツール名を幻覚して
# 呼ぶと ADK が `Tool '...' not found` で ValueError を投げる (multi 系は直接、workflow_graph は
# DynamicNodeFailError でラップ) — これは「モデルの選択ミス」であってインフラ障害ではないので、
# error record として集計除外すると multi 系に有利なバイアスがかかる。よって専用フィールド
# ``agent_error`` で「集計に含める失敗」として分類する (report.is_scored 参照)。transient API
# エラー (429/503/timeout 等) や設定バグ (rerun_on_resume 等) はこのパターンに当たらず除外のまま。
_TOOL_NOT_FOUND_RE = re.compile(r"tool ['\"].+?['\"] not found", re.IGNORECASE)


def _classify_agent_error(error: str | None) -> str | None:
    """error 文字列を「エージェント挙動起因 (集計に含める) か否か」に分類する。

    現状はツール幻覚 (存在しないツール名を呼んで `Tool '...' not found`) のみを agent 起因として
    拾う。該当すれば ``"tool_hallucination"``、それ以外 (インフラ起因/設定バグ) は None を返す。
    """
    if error and _TOOL_NOT_FOUND_RE.search(error):
        return "tool_hallucination"
    return None


def score_record(task: Task | None, final: str, tool_names: list[str],
                 error: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    """1 record 分の採点フィールドを計算する — run_eval と rescore の共有実装。

    trajectory 指標 (trap_hit / route_ok / offtask_calls / selection) は **実ツール呼び出しのみ**で
    判定する (委譲呼び出し *_assistant / transfer_to_agent と skill メタツールを除外) — これにより
    single / multi_agenttool / multi_transfer / single_skills が同じ trajectory を同じスコアにする。
    委譲は別フィールド ``delegations`` (routed domains) に保存する。error record は採点せず
    passed=False / route_ok=None を返す。task.check の例外は fail 扱いで score_error に記録する。
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
    # refused ゲート: E 以外で capability 拒否フレーズを含む応答は不正解にする。要求トークンを
    # エコーしつつ「できません」と拒否した回答が数値照合で PASS する穴を封鎖する。E は不能表明が
    # 正解挙動なので現行の _states_inability ロジックに委ねる (ここでは触らない)。
    if scoreable and task.category != "E" and refused:
        passed = False

    gold = task.gold_tools if task else frozenset()
    expected = task.expected_domains if task else frozenset()
    real = real_tool_names(tool_names)
    called = called_domains(tool_names)
    route_ok = called == expected if scoreable else None

    trap_hit = has_distractor_call(tool_names)
    trap_fatal = trap_hit and not passed
    offtask_calls = sum(1 for n in real if n not in gold) if task else len(real)
    fabricated = bool(scoreable and task.category == "E" and _e_fabricated(final, task.id))
    delegations = routed_domains(tool_calls or [])

    if fabricated:
        selection = "fabrication"
    elif trap_hit:
        selection = "wrong_tool"
    elif any(n in gold for n in real):
        selection = "correct_tool"
    else:
        selection = "no_call"

    out = {
        "passed": passed,
        "refused": refused,
        "domains": sorted(called),
        "expected_domains": sorted(expected),
        "route_ok": route_ok,
        "trap_hit": trap_hit,
        "trap_fatal": trap_fatal,
        "offtask_calls": offtask_calls,
        "delegations": delegations,
        "fabricated": fabricated,
        "selection": selection,
    }
    agent_error = _classify_agent_error(error)
    if agent_error:
        # ツール幻覚等のエージェント挙動起因の失敗。error は原因追跡のため残しつつ、集計側
        # (report.is_scored) はこの record を passed=False の採点済みとして pass rate に含める。
        out["agent_error"] = agent_error
    if score_error:
        out["score_error"] = score_error
    return out
