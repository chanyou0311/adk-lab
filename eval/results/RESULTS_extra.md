# 知識配置バリアント評価 — 結果

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 1  ·  variants: 3  ·  tasks: 3
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた tool family (bq/slack) が expected と完全一致した割合 (skill 系呼び出しは無視、C3 は記録のみ)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録、C カテゴリの合否に使用)。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fat_open` | 100% [44%–100%] | 100% | 0% | 7105 | 12.5 | 2.7 | 3.7 | 0 |
| `tool_desc` | 100% [44%–100%] | 100% | 0% | 8587 | 10.8 | 3.3 | 4.0 | 0 |
| `subagents` | 100% [44%–100%] | 100% | 0% | 12362 | 22.4 | 4.7 | 6.7 | 0 |

## カテゴリ別 pass rate

| variant | A | B | D |
| --- | --- | --- | --- |
| `fat_open` | 100% | 100% | 100% |
| `tool_desc` | 100% | 100% | 100% |
| `subagents` | 100% | 100% | 100% |

## タスク別 pass rate

| task | `fat_open` | `tool_desc` | `subagents` |
| --- | --- | --- | --- |
| A1 | 100% | 100% | 100% |
| B2 | 100% | 100% | 100% |
| D1 | 100% | 100% | 100% |
