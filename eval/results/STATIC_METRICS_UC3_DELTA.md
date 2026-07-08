# UC3 (support-sla) 追加による静的トークン増分 (before → after)

- model: `gemini-3-flash-preview`  ·  token count method: `count_tokens`
- **before** = コミット `4db58d7` (2 ユースケース: sales-analytics / slack-ops)。**after** = UC3 (support-sla) 追加後。
- 各層は「毎リクエストに積まれる固定コンテキスト」。skill L1 は SkillToolset が注入する `<available_skills>` XML (name+description) のトークン量で概算 (L2 本文は load_skill 時のみのオンデマンドで固定コストに含めない)。before の skill L1 は UC3 追加前 2 skill の XML を同じ count_tokens で実測。
- 「ユースケース追加コスト」= Δ固定合計。fat 系は毎回 root に、tool_desc は tool 宣言に、subagents は sub-agent instruction に、skills は L1 だけに乗る。thin_none は 0 (ただし UC3 知識タスクは解けない)。

| variant | root instr Δ | sub instr Δ | tool decl Δ | skill L1 Δ | 固定合計 Δ | before→after 合計 |
| --- | --- | --- | --- | --- | --- | --- |
| `fat_closed` | +98 | +0 | +0 | +0 | **+98** | 768→866 |
| `fat_open` | +98 | +0 | +0 | +0 | **+98** | 878→976 |
| `thin_none` | +0 | +0 | +0 | +0 | **+0** | 596→596 |
| `tool_desc` | +0 | +0 | +90 | +0 | **+90** | 969→1059 |
| `subagents` | +0 | +76 | +5 | +0 | **+81** | 974→1055 |
| `skills` | +0 | +0 | +0 | +37 | **+37** | 1179→1216 |
