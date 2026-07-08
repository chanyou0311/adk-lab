# 静的コスト計測 (固定コンテキストのトークン量)

- model: `gemini-3-flash-preview`  ·  token count method: `count_tokens`
- 「固定」= 毎 LLM リクエストに積まれる層: root instruction / sub-agent instruction+tool 宣言 (sub 側リクエスト) / root tool 宣言 / skill boilerplate (SkillToolset の定型 system instruction)。
- skill L1 XML (<available_skills>) は system instruction には注入されず list_skills のツール応答として返るため、固定合計外の **オンデマンド** 列として別掲する。

| variant | root instr (tok) | sub instr (tok) | sub tool decl (tok) | tool decl (tok) | skill boilerplate (tok) | **固定合計 (tok)** | (参考) skill L1 XML on-demand |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `fat_closed` | 462 | 0 | 0 | 404 | 0 | **866** | 0 |
| `fat_open` | 572 | 0 | 0 | 404 | 0 | **976** | 0 |
| `thin_none` | 192 | 0 | 0 | 404 | 0 | **596** | 0 |
| `tool_desc` | 192 | 0 | 0 | 867 | 0 | **1059** | 0 |
| `subagents` | 226 | 683 | 404 | 146 | 0 | **1459** | 0 |
| `skills` | 192 | 0 | 0 | 878 | 478 | **1548** | 146 |
