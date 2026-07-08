# adk-lab

Google ADK (Agent Development Kit) の実験場。エージェント設計に関する問いを、
再現可能な実験ハーネス + 決定的な採点で定量検証する。

実験ごとに `experiments/<name>/` に自己完結した uv プロジェクトを置く
(依存・実行方法・結果は各実験の README を参照)。

## 実験一覧

| 実験 | 問い | 状態 |
|---|---|---|
| [knowledge-placement](experiments/knowledge-placement/) | ドメイン知識をどこに置くと、root instruction を薄く保ちつつタスク品質を維持できるか (6 配置バリアント × 16 タスクの比較) | 完了 |

## 実験の追加方法

1. `experiments/<name>/` を作り、独立した uv プロジェクト (pyproject.toml) として初期化する
2. fixtures・採点・結果 (JSON/Markdown) をリポジトリに commit し、再現可能に保つ
3. この README の実験一覧に 1 行追加する
