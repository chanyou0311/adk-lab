# 知識配置バリアント評価 — 結果

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 2  ·  variants: 1  ·  tasks: 4
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた tool family (bq/slack) が expected と完全一致した割合 (skill 系呼び出しは無視、C3 は記録のみ)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録、C カテゴリの合否に使用)。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `single_flat@clean` | 100% [68%–100%] | 100% | 0% | 10570 | 15.0 | 6.5 | 6.6 | 0 |

## カテゴリ別 pass rate

| variant | B | C |
| --- | --- | --- |
| `single_flat@clean` | 100% | 100% |

## タスク別 pass rate

| task | `single_flat@clean` |
| --- | --- |
| B1 | 100% |
| B2 | 100% |
| B3 | 100% |
| C1 | 100% |
