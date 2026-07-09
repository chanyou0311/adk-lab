# 知識配置バリアント評価 — 結果 (再採点: results_probe2.json)

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 2  ·  cells: 1  ·  tasks: 4
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた実ツールのドメインが expected と完全一致した割合 (委譲呼び出し *_assistant / transfer_to_agent と skill メタは無視)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録)。E 以外は refused=True で不正解にする (refused ゲート)。

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
