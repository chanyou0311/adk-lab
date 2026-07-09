# adk-lab

Google ADK (Agent Development Kit) の実験場。エージェント設計に関する問いを、
再現可能な実験ハーネス + 決定的な採点で定量検証する。

実験ごとに `experiments/<name>/` に自己完結した uv プロジェクトを置く
(依存・実行方法・結果は各実験の README を参照)。

## 実験一覧

| 実験 | 問い | 状態 |
|---|---|---|
| [knowledge-placement](experiments/knowledge-placement/) | ドメイン知識をどこに置くと、root instruction を薄く保ちつつタスク品質を維持できるか (6 配置バリアント × 16 タスクの比較) | 完了 |
| [agent-composition](experiments/agent-composition/) | 単一 LLM エージェント vs multi-agent 構成 — 単一は「紛らわしさ」で壊れるのか、分割の対価は品質でなくトークンコストか | WIP |

## 実験の追加方法

1. `experiments/<name>/` を作り、独立した uv プロジェクト (pyproject.toml + uv.lock) として初期化する
2. **[AGENTS.md](AGENTS.md) の「実験の再現性チェックリスト」を満たす** — 決定的 fixture (生成物 commit)・
   raw record 全量保存・オフライン再採点器 (rescore)・採点器のユニットテスト・モデル/依存 pin・
   runs≥10 + Wilson CI
3. この README の実験一覧に 1 行追加する

CI (`.github/workflows/ci.yml`) が `experiments/*/` ごとに ruff / pytest / **rescore 冪等性**
(コミット済み再採点結果と現行採点器の一致) をオフラインで検証する。
