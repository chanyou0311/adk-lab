# 静的コスト計測 (固定コンテキストのトークン量)

- model: `gemini-3-flash-preview`  ·  token count method: `count_tokens`
- root instruction / sub-agent instruction / tool declaration に分けて、毎リクエスト積まれる固定コンテキストを測る。

| variant | root instr (chars) | root instr (tok) | sub-agent instr (tok) | tool decl (tok) | skill L1 (tok) | 固定合計 (tok) |
| --- | --- | --- | --- | --- | --- | --- |
| `fat_closed` | 1165 | 462 | 0 | 404 | 0 | 866 |
| `fat_open` | 1730 | 572 | 0 | 404 | 0 | 976 |
| `thin_none` | 962 | 192 | 0 | 404 | 0 | 596 |
| `tool_desc` | 962 | 192 | 0 | 867 | 0 | 1059 |
| `subagents` | 1117 | 226 | 683 | 146 | 0 | 1055 |
| `skills` | 962 | 192 | 0 | 878 | 146 | 1216 |
