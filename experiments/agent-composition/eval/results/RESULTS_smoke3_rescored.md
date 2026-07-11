# agent-composition 評価 — 結果 (再採点: results_smoke3.json)

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 1  ·  cells: 2  ·  tasks: 3
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。
- errors 列 = インフラ起因エラー (transient API・設定バグ等) の件数で、pass rate から除外。ツール幻覚 (存在しないツールを呼んで停止) 等のエージェント挙動起因の失敗は agent_error として passed=False で pass rate に含める。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `workflow_graph@clean` | 100% [44%–100%] | 100% | 0% | 2276 | 7.8 | 1.7 | 4.3 | 0 |
| `workflow_graph@confusable` | 100% [44%–100%] | 33% | 0% | 8769 | 16.6 | 8.0 | 11.3 | 0 |

## カテゴリ別 pass rate

| variant | A | C | E |
| --- | --- | --- | --- |
| `workflow_graph@clean` | 100% | 100% | 100% |
| `workflow_graph@confusable` | 100% | 100% | 100% |

## タスク別 pass rate

| task | `workflow_graph@clean` | `workflow_graph@confusable` |
| --- | --- | --- |
| A1 | 100% | 100% |
| C1 | 100% | 100% |
| E1 | 100% | 100% |
