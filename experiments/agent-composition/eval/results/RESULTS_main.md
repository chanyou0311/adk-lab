# agent-composition 評価 — 結果

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 8  ·  cells: 9  ·  tasks: 16
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `single_flat@clean` | 92% [86%–96%] | 84% | 0% | 140815 | 23.2 | 11.4 | 12.0 | 0 |
| `single_flat@distinct` | 95% [89%–97%] | 77% | 0% | 48974 | 12.8 | 6.8 | 7.1 | 0 |
| `single_flat@confusable` | 97% [92%–99%] | 48% | 0% | 13133 | 9.6 | 5.5 | 5.5 | 0 |
| `single_skills@clean` | 98% [93%–99%] | 88% | 0% | 14231 | 12.0 | 6.5 | 7.2 | 0 |
| `single_skills@confusable` | 89% [82%–93%] | 77% | 0% | 16911 | 12.2 | 7.2 | 8.0 | 0 |
| `multi_agenttool@clean` | 97% [92%–99%] | 90% | 0% | 7764 | 16.5 | 6.7 | 9.0 | 1 |
| `multi_agenttool@confusable` | 91% [84%–95%] | 71% | 0% | 16673 | 20.4 | 9.1 | 11.0 | 0 |
| `multi_transfer@clean` | 98% [94%–100%] | 91% | 0% | 7660 | 9.7 | 4.6 | 5.7 | 0 |
| `multi_transfer@confusable` | 93% [87%–96%] | 71% | 0% | 7744 | 9.8 | 5.0 | 5.9 | 0 |

## カテゴリ別 pass rate

| variant | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| `single_flat@clean` | 100% | 100% | 100% | 100% | 38% |
| `single_flat@distinct` | 100% | 100% | 94% | 100% | 69% |
| `single_flat@confusable` | 100% | 100% | 91% | 100% | 94% |
| `single_skills@clean` | 100% | 100% | 100% | 100% | 81% |
| `single_skills@confusable` | 100% | 97% | 75% | 100% | 69% |
| `multi_agenttool@clean` | 100% | 100% | 97% | 100% | 80% |
| `multi_agenttool@confusable` | 100% | 100% | 72% | 100% | 81% |
| `multi_transfer@clean` | 100% | 100% | 100% | 100% | 88% |
| `multi_transfer@confusable` | 100% | 100% | 75% | 100% | 94% |

## タスク別 pass rate

| task | `single_flat@clean` | `single_flat@distinct` | `single_flat@confusable` | `single_skills@clean` | `single_skills@confusable` | `multi_agenttool@clean` | `multi_agenttool@confusable` | `multi_transfer@clean` | `multi_transfer@confusable` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| A2 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| A3 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| A4 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| B1 | 100% | 100% | 100% | 100% | 88% | 100% | 100% | 100% | 100% |
| B2 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| B3 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| B4 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| C1 | 100% | 100% | 100% | 100% | 100% | 100% | 88% | 100% | 100% |
| C2 | 100% | 88% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| C3 | 100% | 88% | 62% | 100% | 0% | 100% | 0% | 100% | 0% |
| C4 | 100% | 100% | 100% | 100% | 100% | 88% | 100% | 100% | 100% |
| D1 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| D2 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| E1 | 50% | 75% | 88% | 75% | 50% | 86% | 75% | 100% | 88% |
| E2 | 25% | 62% | 100% | 88% | 88% | 75% | 88% | 75% | 100% |
