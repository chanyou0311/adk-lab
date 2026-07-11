# agent-composition 評価 — 結果

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 8  ·  cells: 4  ·  tasks: 16
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。
- errors 列 = インフラ起因エラー (transient API・設定バグ等) の件数で、pass rate から除外。ツール幻覚 (存在しないツールを呼んで停止) 等のエージェント挙動起因の失敗は agent_error として passed=False で pass rate に含める。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `multi_taskmode@clean` | 98% [94%–100%] | 90% | 0% | 10532 | 16.2 | 6.8 | 9.1 | 0 |
| `multi_taskmode@confusable` | 88% [81%–93%] | 73% | 0% | 25558 | 19.5 | 9.9 | 11.9 | 2 |
| `workflow_graph@clean` | 77% [69%–84%] | 100% | 0% | 10670 | 12.9 | 4.9 | 8.0 | 5 |
| `workflow_graph@confusable` | 72% [64%–79%] | 67% | 0% | 11965 | 16.7 | 7.2 | 9.7 | 1 |

## カテゴリ別 pass rate

| variant | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| `multi_taskmode@clean` | 100% | 97% | 100% | 100% | 94% |
| `multi_taskmode@confusable` | 100% | 88% | 75% | 100% | 79% |
| `workflow_graph@clean` | 100% | 52% | 100% | 6% | 100% |
| `workflow_graph@confusable` | 100% | 44% | 100% | 0% | 93% |

## タスク別 pass rate

| task | `multi_taskmode@clean` | `multi_taskmode@confusable` | `workflow_graph@clean` | `workflow_graph@confusable` |
| --- | --- | --- | --- | --- |
| A1 | 100% | 100% | 100% | 100% |
| A2 | 100% | 100% | 100% | 100% |
| A3 | 100% | 100% | 100% | 100% |
| A4 | 100% | 100% | 100% | 100% |
| B1 | 100% | 75% | 75% | 62% |
| B2 | 88% | 75% | 14% | 0% |
| B3 | 100% | 100% | 25% | 12% |
| B4 | 100% | 100% | 100% | 100% |
| C1 | 100% | 100% | 100% | 100% |
| C2 | 100% | 100% | 100% | 100% |
| C3 | 100% | 0% | 100% | 100% |
| C4 | 100% | 100% | 100% | 100% |
| D1 | 100% | 100% | 12% | 0% |
| D2 | 100% | 100% | 0% | 0% |
| E1 | 100% | 83% | 100% | 86% |
| E2 | 88% | 75% | 100% | 100% |
