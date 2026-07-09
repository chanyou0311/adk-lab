# 知識配置バリアント評価 — 結果 (再採点: results_smoke.json)

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 1  ·  cells: 9  ·  tasks: 3
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `single_flat@clean` | 67% [21%–94%] | 67% | 0% | 10627 | 12.0 | 7.0 | 8.0 | 0 |
| `single_flat@distinct` | 33% [6%–79%] | 67% | 0% | 6735 | 8.8 | 6.0 | 5.0 | 0 |
| `single_flat@confusable` | 67% [21%–94%] | 33% | 0% | 11134 | 11.6 | 6.3 | 7.3 | 0 |
| `single_skills@clean` | 67% [21%–94%] | 67% | 0% | 17719 | 14.2 | 8.0 | 9.0 | 0 |
| `single_skills@confusable` | 67% [21%–94%] | 67% | 0% | 23539 | 14.5 | 10.7 | 9.3 | 0 |
| `multi_agenttool@clean` | 67% [21%–94%] | 67% | 0% | 3882 | 10.1 | 4.0 | 6.3 | 0 |
| `multi_agenttool@confusable` | 67% [21%–94%] | 67% | 0% | 4835 | 10.8 | 5.3 | 6.3 | 0 |
| `multi_transfer@clean` | 67% [21%–94%] | 67% | 0% | 6893 | 10.8 | 6.0 | 6.0 | 0 |
| `multi_transfer@confusable` | 67% [21%–94%] | 67% | 0% | 6454 | 7.8 | 4.7 | 5.7 | 0 |

## カテゴリ別 pass rate

| variant | A | C | E |
| --- | --- | --- | --- |
| `single_flat@clean` | 100% | 0% | 100% |
| `single_flat@distinct` | 100% | 0% | 0% |
| `single_flat@confusable` | 100% | 0% | 100% |
| `single_skills@clean` | 100% | 0% | 100% |
| `single_skills@confusable` | 100% | 0% | 100% |
| `multi_agenttool@clean` | 100% | 0% | 100% |
| `multi_agenttool@confusable` | 100% | 0% | 100% |
| `multi_transfer@clean` | 100% | 0% | 100% |
| `multi_transfer@confusable` | 100% | 0% | 100% |

## タスク別 pass rate

| task | `single_flat@clean` | `single_flat@distinct` | `single_flat@confusable` | `single_skills@clean` | `single_skills@confusable` | `multi_agenttool@clean` | `multi_agenttool@confusable` | `multi_transfer@clean` | `multi_transfer@confusable` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| C1 | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 0% |
| E1 | 100% | 0% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
