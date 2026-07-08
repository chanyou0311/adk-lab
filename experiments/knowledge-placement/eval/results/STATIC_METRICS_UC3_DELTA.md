# UC3 (support-sla) 追加による静的トークン増分 (before → after)

- model: `gemini-3-flash-preview`  ·  token count method: `count_tokens`
- **before** = コミット `4db58d7` (2 ユースケース: sales-analytics / slack-ops)。**after** = UC3 (support-sla) 追加後。
- 計測方法 (レビューで修正済み): 「固定」= 毎 LLM リクエストに積まれる層のみ。
  - **skill boilerplate** (SkillToolset が毎リクエスト注入する定型 system instruction、478 tok) を固定層として計上する。ADK 2.4.0 では `<available_skills>` XML (L1) は **system instruction に注入されない** (list_skills ツールが存在するため) — L1 XML は `list_skills` のツール応答として返る **オンデマンド** コストであり、固定合計から除外して別掲する。
  - **subagents の sub-agent 側 tool 宣言** (404 tok) も固定層として計上する (sub-agent の LLM リクエストに毎回積まれる。instruction だけ数えて宣言を落とすと層の数え方がバリアント間で非対称になる)。
  - boilerplate と sub 側 tool 宣言は UC 数に依存しない定数のため、before 値は after と同値 (boilerplate=478 / sub tool decl=404)。L1 XML の before (2 skills) は 109 tok を同じ count_tokens で実測。その他の before 値は `4db58d7` の static_metrics.json より。
- 「ユースケース追加コスト」= Δ固定合計。fat 系は root に、tool_desc は tool 宣言に、subagents は sub-agent instruction に乗る。**skills の固定増分は 0** (知識は L2 本文に置かれ、L1 メタデータもオンデマンド) — 引き換えに boilerplate 478 tok の常時オーバーヘッドと、load_skill 時の L2 実行時コストを払う。thin_none は +0 だが UC3 知識タスクは解けない。

| variant | root instr Δ | sub instr Δ | sub tool decl Δ | tool decl Δ | skill boilerplate Δ | **固定合計 Δ** | before→after 固定合計 | (参考) L1 XML on-demand Δ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fat_closed` | +98 | +0 | +0 | +0 | +0 | **+98** | 768→866 | – |
| `fat_open` | +98 | +0 | +0 | +0 | +0 | **+98** | 878→976 | – |
| `thin_none` | +0 | +0 | +0 | +0 | +0 | **+0** | 596→596 | – |
| `tool_desc` | +0 | +0 | +0 | +90 | +0 | **+90** | 969→1059 | – |
| `subagents` | +0 | +76 | +0 | +5 | +0 | **+81** | 1378→1459 | – |
| `skills` | +0 | +0 | +0 | +0 | +0 | **+0** | 1548→1548 | 109→146 (+37) |

補足: 固定合計の絶対値は skills が最大 (1548 tok — boilerplate の常時負担)。「UC を足すたびに増えるか」(Δ) と「常時いくら払うか」(絶対値) は別軸であり、skills は Δ最小・絶対値最大のトレードオフになる。実行時の実測トークン (RESULTS) と併せて読むこと。
