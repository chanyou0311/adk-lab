# agent-composition 評価 — 結果 (再採点: results_graph2.json)

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 8  ·  cells: 2  ·  tasks: 16
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。
- errors 列 = インフラ起因エラー (transient API・設定バグ等) の件数で、pass rate から除外。ツール幻覚 (存在しないツールを呼んで停止) 等のエージェント挙動起因の失敗は agent_error として passed=False で pass rate に含める。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `workflow_graph@clean` | 80% [73%–86%] | 100% | 2% | 8852 | 14.4 | 4.6 | 7.9 | 0 |
| `workflow_graph@confusable` | 75% [67%–82%] | 70% | 0% | 26995 | 18.4 | 7.7 | 10.5 | 3 |

## カテゴリ別 pass rate

| variant | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| `workflow_graph@clean` | 100% | 59% | 94% | 38% | 100% |
| `workflow_graph@confusable` | 100% | 70% | 62% | 38% | 100% |

## タスク別 pass rate

| task | `workflow_graph@clean` | `workflow_graph@confusable` |
| --- | --- | --- |
| A1 | 100% | 100% |
| A2 | 100% | 100% |
| A3 | 100% | 100% |
| A4 | 100% | 100% |
| B1 | 100% | 100% |
| B2 | 38% | 38% |
| B3 | 12% | 33% |
| B4 | 88% | 100% |
| C1 | 100% | 100% |
| C2 | 75% | 50% |
| C3 | 100% | 0% |
| C4 | 100% | 100% |
| D1 | 75% | 75% |
| D2 | 0% | 0% |
| E1 | 100% | 100% |
| E2 | 100% | 100% |
