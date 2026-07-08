# 静的コスト計測 (固定コンテキストのトークン量)

- model: `gemini-3-flash-preview`  ·  token count method: `count_tokens`
- root instruction / sub-agent instruction / tool declaration に分けて、毎リクエスト積まれる固定コンテキストを測る。

| variant | root instr (chars) | root instr (tok) | sub-agent instr (tok) | tool decl (tok) | 固定合計 (tok) |
| --- | --- | --- | --- | --- | --- |
| `fat_closed` | 955 | 364 | 0 | 404 | 768 |
| `fat_open` | 1520 | 474 | 0 | 404 | 878 |
| `thin_none` | 962 | 192 | 0 | 404 | 596 |
| `tool_desc` | 962 | 192 | 0 | 777 | 969 |
| `subagents` | 1117 | 226 | 607 | 141 | 974 |
| `skills` | 962 | 192 | 0 | 878 | 1070 |
