"""収集 4 tag の rescored 結果をマージして統合レポート (RESULTS_canonical.md) を再生成する。

ブログ記事のスコアボードはこのレポートが正本。収集は 4 tag に分かれている:

- `_main`   : 本収集第 1 波 (single_flat×3env + single_skills/multi_agenttool/multi_transfer×2env = 9 セル)
- `_main2`  : multi_taskmode の追加収集。**同 tag の workflow_graph 2 セルは planner 修正前の
              旧実装 (質問全文を各ノードへ配布し越境ツール幻覚でクラッシュ多発) のため統合から
              除外し、`_graph2` が supersede する**
- `_graph2` : workflow_graph の正版 (planner をドメイン別サブクエリ分解に修正後)
- `_ctopup` : C カテゴリ 4 タスクの追い足し (confusable × 6 バリアント × 8 runs、cap=120)。
              C 列と trap 系の裏付け数値だけに合流し、pass 総合とコスト分布には混ぜない
              (cap 有無の収集条件差をコスト分布へ持ち込まないため)

raw record は append-only。本ファイルの出力は派生成果物で、いつでも決定的に再生成できる
(タイムスタンプ等の非決定要素は出力しない)。

Usage:
    uv run python eval/canonical_report.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
sys.path.insert(0, str(EVAL_DIR))

from report import aggregate, is_scored, mean, pct, wilson  # noqa: E402

BASE_TAGS = ("_main", "_main2", "_graph2")
TOPUP_TAG = "_ctopup"
# _main2 のうち統合するバリアント (workflow_graph は _graph2 が supersede)
MAIN2_KEEP = {"multi_taskmode"}
EXPECTED_CELLS = 13
MODEL = "gemini-3-flash-preview"
ADK_PIN = "google-adk==2.4.0"


def _load(tag: str) -> list[dict]:
    return json.loads(
        (RESULTS_DIR / f"results{tag}_rescored.json").read_text(encoding="utf-8")
    )["records"]


def merge_base() -> list[dict]:
    """本収集 3 tag を supersede 規則付きでマージした 13 セルの record 列。"""
    records = _load("_main")
    records += [r for r in _load("_main2") if r["variant"] in MAIN2_KEEP]
    records += _load("_graph2")
    cells = {(r["variant"], r["env"]) for r in records}
    assert len(cells) == EXPECTED_CELLS, f"expected {EXPECTED_CELLS} cells, got {len(cells)}"
    assert {e for v, e in cells if v == "single_flat"} == {"clean", "distinct", "confusable"}
    for v in {v for v, _ in cells} - {"single_flat"}:
        assert {e for vv, e in cells if vv == v} == {"clean", "confusable"}, v
    return records


def load_topup() -> list[dict]:
    """C 追い足し record (全件 C カテゴリ × confusable であることを検証)。"""
    records = _load(TOPUP_TAG)
    assert all(r["category"] == "C" and r["env"] == "confusable" for r in records)
    return records


def _p95(xs: list[float]) -> float:
    """線形補間の 95 パーセンタイル。"""
    s = sorted(xs)
    idx = 0.95 * (len(s) - 1)
    lo = int(idx)
    return s[lo] if lo == len(s) - 1 else s[lo] + (idx - lo) * (s[lo + 1] - s[lo])


def _pass_ci(rows: list[dict]) -> tuple[int, int, float, float]:
    k = sum(1 for r in rows if r["passed"])
    lo, hi = wilson(k, len(rows))
    return k, len(rows), lo, hi


def scoreboard(base: list[dict], topup: list[dict]) -> list[dict]:
    """記事スコアボード (CONFUSABLE) の行データ。pass 降順。"""
    conf = [r for r in base if r["env"] == "confusable" and is_scored(r)]
    top = [r for r in topup if is_scored(r)]
    rows = []
    for v in sorted({r["variant"] for r in conf}):
        vc = [r for r in conf if r["variant"] == v]
        c_rows = [r for r in vc if r["category"] == "C"] + [r for r in top if r["variant"] == v]
        non_e_tok = [r["tokens"] for r in vc if r["category"] != "E"]
        k, n, lo, hi = _pass_ci(vc)
        ck, cn, clo, chi = _pass_ci(c_rows)
        rows.append({
            "variant": v,
            "pass": (k, n, lo, hi),
            "c": (ck, cn, clo, chi),
            "d": mean([1.0 if r["passed"] else 0.0 for r in vc if r["category"] == "D"]),
            "e": mean([1.0 if r["passed"] else 0.0 for r in vc if r["category"] == "E"]),
            "median_tok": statistics.median(non_e_tok),
            "p95_tok": _p95(non_e_tok),
            "mean_tok_all": mean([r["tokens"] for r in vc]),
        })
    return sorted(rows, key=lambda r: r["pass"][0] / r["pass"][1], reverse=True)


def evidence(base: list[dict], topup: list[dict]) -> dict:
    """発見の裏付け数値: C3 自己回復・trap_fatal・E カテゴリの探索コスト。"""
    conf_c = [r for r in base if r["env"] == "confusable" and r["category"] == "C"
              and is_scored(r)] + [r for r in topup if is_scored(r)]
    variants = sorted({r["variant"] for r in conf_c})
    c3 = {v: [r["passed"] for r in conf_c if r["variant"] == v and r["task_id"] == "C3"]
          for v in variants}
    fatal = {v: [bool(r["trap_fatal"]) for r in conf_c if r["variant"] == v] for v in variants}
    e_rows = [r for r in base if r["category"] == "E" and is_scored(r)]
    e_tok = {(r["variant"], r["env"]): [] for r in e_rows}
    for r in e_rows:
        e_tok[(r["variant"], r["env"])].append(r["tokens"])
    return {
        "c3": {v: (sum(xs), len(xs)) for v, xs in c3.items()},
        "trap_fatal": {v: (sum(xs), len(xs)) for v, xs in fatal.items()},
        "e_tokens": {k: mean(v) for k, v in sorted(e_tok.items())},
    }


def _tok(x: float) -> str:
    return f"{x / 1000:.1f}k"


def render(base: list[dict], topup: list[dict]) -> str:
    board = scoreboard(base, topup)
    ev = evidence(base, topup)
    runs = 8
    lines = [
        "# agent-composition 評価 — 統合レポート (canonical)",
        "",
        "ブログ記事 (https://blog.fumo.jp/posts/adk-agent-composition-patterns/) の数値の正本。",
        "`uv run python eval/canonical_report.py` でいつでも決定的に再生成できる (raw record は",
        "append-only、本ファイルは派生成果物)。",
        "",
        f"- model: `{MODEL}` (`{ADK_PIN}`)  ·  runs/(cell,task): {runs} (C カテゴリのみ追い足し込み n=64/構成)",
        "- 供給元: `results_main_rescored.json` + `results_main2_rescored.json` (multi_taskmode のみ)"
        " + `results_graph2_rescored.json` + `results_ctopup_rescored.json`",
        "- マージ規則: `_main2` の workflow_graph 2 セルは planner 修正前の旧実装のため除外し"
        " `_graph2` が supersede。`_ctopup` は C 列と裏付け数値のみに合流し、"
        "pass 総合とコスト分布には混ぜない",
        "- 収集条件差: `_main` (flat/skills/agenttool/transfer) は LLM 呼び出し無制限、"
        "`_main2`/`_graph2`/`_ctopup` (taskmode/graph/C 追い足し) は暴走発見後の cap=120。"
        "cap 到達 record は error として pass 分母から除外 (本レポートの母集団で 6 件)。"
        "無制限の `_main` で 120 超は 7/1152 件・全て E (詳細は README)",
        "- 集計対象は scored record のみ (エージェント挙動起因の失敗は passed=False で含め、"
        "インフラ起因エラーのみ除外 — report.is_scored)",
        "",
        "## 記事スコアボード (CONFUSABLE)",
        "",
        "median/p95 tok は E (答えの存在しない質問) を除く — E の探索暴走が分布を桁単位で歪める"
        "ため。暴走込みの期待コストは mean tok (E 込み) 列を見る。",
        "",
        "| 構成 | pass (95% CI) | C 罠 (95% CI, n) | D | E | median tok (E 除く) "
        "| p95 tok (E 除く) | mean tok (E 込み) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in board:
        k, n, lo, hi = row["pass"]
        ck, cn, clo, chi = row["c"]
        lines.append(
            f"| `{row['variant']}` | {pct(k / n)} [{pct(lo)}–{pct(hi)}] | "
            f"{pct(ck / cn)} [{pct(clo)}–{pct(chi)}] (n={cn}) | {pct(row['d'])} | {pct(row['e'])} | "
            f"{_tok(row['median_tok'])} | {_tok(row['p95_tok'])} | {_tok(row['mean_tok_all'])} |"
        )
    lines += [
        "",
        "## 発見の裏付け数値",
        "",
        "### C3 (データカタログ罠) の自己回復 — confusable、base+追い足し",
        "",
        "| variant | passed / n |",
        "| --- | --- |",
    ]
    for v, (k, n) in ev["c3"].items():
        lines.append(f"| `{v}` | {k}/{n} |")
    lines += [
        "",
        "### trap_fatal (C カテゴリで罠を踏んだまま終了) — confusable、base+追い足し",
        "",
        "| variant | trap_fatal / n |",
        "| --- | --- |",
    ]
    for v, (k, n) in ev["trap_fatal"].items():
        lines.append(f"| `{v}` | {k}/{n} |")
    lines += [
        "",
        "### E カテゴリ (irrelevance) の mean tokens — 探索暴走の env 依存",
        "",
        "| variant | env | mean tokens |",
        "| --- | --- | --- |",
    ]
    for (v, env), tok in ev["e_tokens"].items():
        lines.append(f"| `{v}` | {env} | {tok:,.0f} |")
    cells = sorted({r["cell"] for r in base})
    categories = sorted({r["category"] for r in base})
    summary = aggregate(base, cells, categories, group_field="cell")
    lines += [
        "",
        "## セル別サマリ (13 セル)",
        "",
        "| cell | pass (95% CI) | route ok | refusal | mean tokens | latency(s) | errors |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell in cells:
        s = summary[cell]
        lo, hi = s["pass_ci"]
        lines.append(
            f"| `{cell}` | {pct(s['pass_rate'])} [{pct(lo)}–{pct(hi)}] | {pct(s['route_ok_rate'])} | "
            f"{pct(s['refusal_rate'])} | {s['tokens']:,.0f} | {s['latency']:.1f} | {s['n_error']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    base = merge_base()
    topup = load_topup()
    md = render(base, topup)
    out = RESULTS_DIR / "RESULTS_canonical.md"
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out.name}")
    print(md.split("## 発見の裏付け数値")[0])


if __name__ == "__main__":
    main()
