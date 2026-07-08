# 知識配置バリアント評価 — 結果 (再採点: results_uc3.json)

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 10  ·  variants: 6  ·  tasks: 2
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた tool family (bq/slack) が expected と完全一致した割合 (skill 系呼び出しは無視、C3 は記録のみ)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録、C カテゴリの合否に使用)。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fat_closed` | 95% [76%–99%] | 100% | 0% | 11878 | 17.4 | 4.8 | 5.8 | 0 |
| `fat_open` | 90% [70%–97%] | 100% | 0% | 16906 | 19.2 | 5.8 | 6.8 | 0 |
| `thin_none` | 0% [0%–16%] | 0% | 0% | 248212 | 220.6 | 33.1 | 34.1 | 0 |
| `tool_desc` | 100% [84%–100%] | 100% | 0% | 12036 | 16.8 | 4.6 | 5.6 | 0 |
| `subagents` | 75% [53%–89%] | 100% | 0% | 12104 | 21.4 | 5.8 | 7.8 | 0 |
| `skills` | 100% [84%–100%] | 50% | 0% | 23808 | 21.5 | 8.1 | 9.1 | 0 |

## カテゴリ別 pass rate

| variant | F |
| --- | --- |
| `fat_closed` | 95% |
| `fat_open` | 90% |
| `thin_none` | 0% |
| `tool_desc` | 100% |
| `subagents` | 75% |
| `skills` | 100% |

## タスク別 pass rate

| task | `fat_closed` | `fat_open` | `thin_none` | `tool_desc` | `subagents` | `skills` |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | 100% | 100% | 0% | 100% | 100% | 100% |
| F2 | 90% | 80% | 0% | 100% | 50% | 100% |
