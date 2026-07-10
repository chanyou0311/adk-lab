# 知識配置バリアント評価 — 結果 (再採点: results_ctopup.json)

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 8  ·  cells: 6  ·  tasks: 4
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。
- errors 列 = インフラ起因エラー (transient API・設定バグ等) の件数で、pass rate から除外。ツール幻覚 (存在しないツールを呼んで停止) 等のエージェント挙動起因の失敗は agent_error として passed=False で pass rate に含める。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `single_flat@confusable` | 88% [72%–95%] | 34% | 0% | 5465 | 5.5 | 3.0 | 3.7 | 0 |
| `single_skills@confusable` | 75% [58%–87%] | 53% | 0% | 9141 | 6.8 | 4.4 | 5.2 | 0 |
| `multi_agenttool@confusable` | 75% [58%–87%] | 44% | 0% | 6908 | 11.5 | 6.8 | 7.9 | 0 |
| `multi_transfer@confusable` | 75% [58%–87%] | 28% | 0% | 5782 | 6.4 | 4.1 | 5.0 | 0 |
| `multi_taskmode@confusable` | 61% [44%–76%] | 35% | 0% | 49118 | 25.5 | 14.9 | 16.2 | 1 |
| `workflow_graph@confusable` | 59% [42%–74%] | 25% | 0% | 13658 | 16.6 | 8.4 | 9.8 | 0 |

## カテゴリ別 pass rate

| variant | C |
| --- | --- |
| `single_flat@confusable` | 88% |
| `single_skills@confusable` | 75% |
| `multi_agenttool@confusable` | 75% |
| `multi_transfer@confusable` | 75% |
| `multi_taskmode@confusable` | 61% |
| `workflow_graph@confusable` | 59% |

## タスク別 pass rate

| task | `single_flat@confusable` | `single_skills@confusable` | `multi_agenttool@confusable` | `multi_transfer@confusable` | `multi_taskmode@confusable` | `workflow_graph@confusable` |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | 100% | 100% | 100% | 100% | 88% | 100% |
| C2 | 88% | 100% | 100% | 100% | 71% | 25% |
| C3 | 62% | 0% | 0% | 0% | 0% | 12% |
| C4 | 100% | 100% | 100% | 100% | 88% | 100% |
