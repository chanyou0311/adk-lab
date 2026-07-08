# AGENTS.md

Google ADK の実験場。エージェント設計に関する問いを、再現可能な実験ハーネス +
決定的な採点で定量検証する。実験は `experiments/<name>/` に自己完結した
uv プロジェクトとして置く。

## 実験の再現性チェックリスト (新規実験の必須要素)

1. **決定的 fixture**: seed 固定・**生成物を commit**・GT 健全性を pytest で固定。
   既存 fixture への追加生成は独立 RNG (`random.Random(SEED + n)`) を使い、
   既存ファイルをバイト不変に保つ
2. **raw record の全量保存**: 最終応答の全文・tool trajectory・トークン・レイテンシを
   results JSON に残す (採点に使わないものも含めて)。model id / runs も記録する
3. **オフライン再採点器 (rescore) を最初から作る**: 採点器は必ずバグる。保存済み record に
   現行採点器を再適用して結果を更新できる構造 (LLM 再実行なし) が生命線
4. **採点器のユニットテスト**: 正例に加えて **gaming 例** (見つけた定義への接地・捏造閾値で
   偶然正解を包含) と **terse-correct 例** (正しいが簡潔で marker を欠く回答) の両側を固定する
5. **pin**: モデルは明示 pin (preview の alias 禁止)・`temperature=0`・依存は `==` pin +
   uv.lock を commit (`uv sync --frozen` が通ること)
6. **統計**: runs≥10 + Wilson 95% CI。n が小さいセルの差から結論を書かない

## エージェント制約 (MUST)

- **`eval/results/` の過去記録は改変禁止 (append-only)**。再採点は `_rescored` サフィックスの
  別ファイルへ。実験をやり直す場合も tag を変えて追加する
- **採点器を変更したら、コミット済みの全 tag を rescore で再採点**し、before/after を PR に
  明記する (CI が `results_*_rescored` と採点器の byte 一致を強制する — 再生成漏れは落ちる)
- **LLM を呼ぶ eval (run_eval.py 等) は課金があるため、明示指示があるときのみ実行**する。
  ruff / pytest / rescore / 静的検証はオフラインなので自由に実行してよい
- **フレームワーク内部挙動を計測の前提にするときは、ソースを読んで検証してから**
  (例: 「SkillToolset が何を system instruction に注入するか」は仮定せず実装で確認する。
  ADK ソースは `.venv/lib/python*/site-packages/google/adk/`)
- 結果の解釈を変える修正 (採点器・計測方法論) は、影響する数値の before/after を
  PR description に書く

## CI (.github/workflows/ci.yml)

`experiments/*/` ごとに完全オフラインで実行: `uv sync --frozen` → `ruff` → `pytest` →
**rescore 冪等性** (コミット済み `results_*_rescored.*` を現行採点器で再生成し
`git diff --exit-code`)。Vertex / secrets には依存しない。

## 共有ライブラリ化の方針

実験間のコード共有 (report.py / rescore.py / MetricsPlugin / _GlobalGemini が候補) は
**2 つ目の実験が現れてから**昇格する (rule of three)。1 実験の時点での抽象化は
当てずっぽうの API になるため行わない。実験手順の Skill 化・scaffold スクリプトも同様に、
実験追加が 2〜3 回繰り返されて型が安定してから検討する。
