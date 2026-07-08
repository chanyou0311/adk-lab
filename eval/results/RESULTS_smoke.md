# 知識配置バリアント評価 — 結果

- model: `gemini-3-flash-preview`  ·  runs/(variant,task): 1  ·  variants: 3  ·  tasks: 4
- pass rate は Wilson 95% CI 付き。route ok = 呼ばれた tool family (bq/slack) が expected と完全一致した割合 (skill 系呼び出しは無視、C3 は記録のみ)。
- refusal rate = capability 拒否フレーズを含んだ応答の割合 (全タスクで記録、C カテゴリの合否に使用)。

## バリアント別サマリ

| variant | pass (95% CI) | route ok | refusal | tokens | latency(s) | tool calls | LLM calls | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fat_closed` | 100% [51%–100%] | 100% | 0% | 3310 | 6.3 | 1.8 | 2.8 | 0 |
| `thin_none` | 75% [30%–95%] | 100% | 0% | 3553 | 8.1 | 3.5 | 3.2 | 0 |
| `skills` | 100% [51%–100%] | 100% | 0% | 11171 | 12.2 | 4.0 | 5.0 | 0 |

## カテゴリ別 pass rate

| variant | A | D | E |
| --- | --- | --- | --- |
| `fat_closed` | 100% | 100% | 100% |
| `thin_none` | 100% | 100% | 0% |
| `skills` | 100% | 100% | 100% |

## タスク別 pass rate

| task | `fat_closed` | `thin_none` | `skills` |
| --- | --- | --- | --- |
| A1 | 100% | 100% | 100% |
| A3 | 100% | 100% | 100% |
| D1 | 100% | 100% | 100% |
| E2 | 100% | 0% | 100% |
