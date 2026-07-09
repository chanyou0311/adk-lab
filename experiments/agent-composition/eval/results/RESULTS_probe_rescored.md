# 知識配置バリアント評価 — 結果 (再採点: results_probe.json)

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 1  ·  variants: 4  ·  tasks: 16
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた tool family (bq/slack) が expected と完全一致した割合 (skill 系呼び出しは無視、C3 は記録のみ)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録、C カテゴリの合否に使用)。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `single_flat@clean` | 100% [81%–100%] | 81% | 0% | 6096 | 10.4 | 4.3 | 5.2 | 0 |
| `single_flat@confusable` | 100% [81%–100%] | 81% | 0% | 8921 | 8.4 | 4.4 | 5.0 | 0 |
| `multi_agenttool@clean` | 100% [34%–100%] | 100% | 0% | 10003 | 23.3 | 8.5 | 12.5 | 0 |
| `multi_agenttool@confusable` | 100% [34%–100%] | 100% | 0% | 9780 | 21.5 | 7.0 | 11.5 | 0 |

## カテゴリ別 pass rate

| variant | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| `single_flat@clean` | 100% | 100% | 100% | 100% | 100% |
| `single_flat@confusable` | 100% | 100% | 100% | 100% | 100% |
| `multi_agenttool@clean` | 0% | 0% | 0% | 100% | 0% |
| `multi_agenttool@confusable` | 0% | 0% | 0% | 100% | 0% |

## タスク別 pass rate

| task | `single_flat@clean` | `single_flat@confusable` | `multi_agenttool@clean` | `multi_agenttool@confusable` |
| --- | --- | --- | --- | --- |
| A1 | 100% | 100% | 0% | 0% |
| A2 | 100% | 100% | 0% | 0% |
| A3 | 100% | 100% | 0% | 0% |
| A4 | 100% | 100% | 0% | 0% |
| B1 | 100% | 100% | 0% | 0% |
| B2 | 100% | 100% | 0% | 0% |
| B3 | 100% | 100% | 0% | 0% |
| B4 | 100% | 100% | 0% | 0% |
| C1 | 100% | 100% | 0% | 0% |
| C2 | 100% | 100% | 0% | 0% |
| C3 | 100% | 100% | 0% | 0% |
| C4 | 100% | 100% | 0% | 0% |
| D1 | 100% | 100% | 100% | 100% |
| D2 | 100% | 100% | 100% | 100% |
| E1 | 100% | 100% | 0% | 0% |
| E2 | 100% | 100% | 0% | 0% |
