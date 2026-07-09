# agent-composition

Google ADK (Python) エージェントで、**単一の LLM エージェントと multi-agent 構成 (agent
composition) を統制比較する**実験 ([adk-lab](../../README.md) の実験のひとつ)。

> **状態: WIP (本収集前)。** ハーネス・16 タスク・6 バリアント・3 環境 (CLEAN/DISTINCT/
> CONFUSABLE) を実装済み。V-1 smoke と難度プローブ (単発実行) で計測健全性・採点器・罠の発動を
> 確認済み。**本収集 (runs≥8 の全セル) はこれから。** 較正メモ: gemini-3-flash は強く、多段導出で
> 硬化しても CLEAN ベースラインは天井寄り。品質だけでなく環境劣化・コスト差・trajectory 指標で
> 仮説を検証する設計 (下記「較正と runs 設計」参照)。

## 問い

同じタスクを解かせたとき、**単一の LLM エージェント**と**役割で分割した multi-agent 構成**は、
品質・コスト・失敗モードでどう違うのか。特に次の 2 つの仮説を、統制条件下で定量検証する。

1. **単一エージェントはツールの数ではなく「紛らわしさ」で壊れる** — ツールを増やすこと自体より、
   用途が近く紛らわしいツール・ドメインが混在することが誤ルーティングや過剰拒否を招く、という仮説。
2. **分割の対価は品質ではなくトークンコスト** — multi-agent への分割は品質を上げるより、
   ルーティングと再文脈化のオーバーヘッド (トークン) を増やす方向に効く、という仮説。

## 検証軸 (6 つ)

同一のタスク・モデル・知識のまま、エージェント構成だけを変えて次を決定的に測る。

| # | 軸 | 測るもの |
|---|---|---|
| 1 | 正答率 (quality) | タスク別 pass rate + Wilson 95% CI。trap 発動 (trap_hit/trap_fatal) と捏造 (fabricated) も |
| 2 | トークンコスト | 総トークン + 内訳 (prompt / candidates / **thoughts** / tool-use-prompt / cached) |
| 3 | ルーティング精度 | 呼ばれた**実ツール**のドメインが expected と一致した割合 (route_ok) + 委譲先 (delegations) |
| 4 | 過剰拒否 (refusal) | 能力を「持たない」と誤って拒否した割合。E 以外は refused=True で不正解にする (refused ゲート) |
| 5 | レイテンシ・LLM 呼び出し数 | ジョブ毎の壁時計時間と LLM 呼び出し回数 |
| 6 | thought signature 健全性 | function_call part の thought_signature 欠落 (per-request 最大 / ever) と起因の 400 発生 |

> trajectory 指標 (trap_hit / route_ok / offtask_calls / selection) は**実ツール呼び出しのみ**で判定
> する — 委譲呼び出し (`*_assistant` / `transfer_to_agent`) と skill メタツールを除外することで、
> single / multi_agenttool / multi_transfer / single_skills が同じ trajectory を同じスコアにする
> (バリアント間の測定を対称にする)。委譲先ドメインは `delegations` に別記録する。

> 6 は Gemini 3 (thinking) 特有の軸。multi-agent (AgentTool) 構成では sub-agent の
> thought signature が親リクエストへ伝播せず 400 になりうるため、欠落を計測して切り分ける。

## モデル

Vertex AI の `gemini-3-flash-preview`。**global エンドポイント限定** (regional は 404) なので
`src/lab/model.py` の `_GlobalGemini` で api_client の location を global に固定する。生成設定は
**temperature=1.0 + thinking_level=LOW** (gemini-3 thinking の既定 temperature を使い、決定性は
runs を増やして統計で吸収する。thinking の粒度は LOW に固定してバリアント間で一定にする)。

## 計測方法 (重要)

トークンと tool 呼び出しは ADK の **Plugin** (`before_model_callback` / `after_model_callback` /
`before_tool_callback`) で収集する。ADK 2.4.0 の `AgentTool` は sub-agent を**別 Runner で実行**
するため、sub-agent 内部の LLM 呼び出し・tool 呼び出しは親の event ストリームには現れない。
Plugin は AgentTool 経由で子 Runner に伝播するので、multi-agent 構成でも root+sub 横断で
トークンと trajectory を漏れなく数えられる (これが唯一の横断計測手段)。

`MetricsPlugin` は標準トークンに加えて Gemini 3 向けに次を独立集計する:
- `thoughts_tokens` / `tool_use_prompt_tokens` / `cached_tokens` (usage_metadata の内訳)
- `signature_missing_max` (各リクエストで欠落した function_call part 数の **リクエスト単位の最大**) /
  `signature_ever_missing` (一度でも欠落したか) — 全履歴を毎リクエスト数えて累積すると超線形に
  膨らむため per-request の値を集約する。smoke ゲートは `ever_missing==False` で判定する
- `signature_400` (thought_signature 起因の 400 でジョブが失敗したか)

streaming の partial レスポンスは usage が二重に来るため、`after_model_callback` の冒頭で
`partial` をガードする。thought part (推論の途中出力) は最終回答テキストから除外する。

## バリアント (6)

同一のタスク・環境・役割文言 (SUBAGENT_PERSONA + OPEN_MANDATE) のまま、**構成 (composition) だけ**を変える。

| variant | 構成 | env |
|---|---|---|
| `single_flat` | 単一 LlmAgent が env の全ツールを直接持つ (基準線) | CLEAN/DISTINCT/CONFUSABLE |
| `single_skills` | SkillToolset でドメイン別ツールをゲーティング (root は直接ツールを持たない) | CLEAN/CONFUSABLE |
| `multi_agenttool` | root + ドメイン別 sub-agent を AgentTool で保持 (LLM が function-calling で委譲) | CLEAN/CONFUSABLE |
| `multi_transfer` | 同じ分割を `sub_agents` (transfer_to_agent) で委譲 | CLEAN/CONFUSABLE |
| `multi_taskmode` | Collaborative task-mode 委譲 (transfer の現代版)。sub-agent を `mode='single_turn'` で `sub_agents=` に接続 → coordinator が `_SingleTurnAgentTool` (name=sub 名) で委譲 | CLEAN/CONFUSABLE |
| `workflow_graph` | ADK 2.4.0 の Workflow (graph) エンジン。planner→dispatcher→synthesizer の spine、planner が構造化出力でドメインを選び dispatcher が `ctx.run_node` で専門ノードを動的実行 | CLEAN/CONFUSABLE |

> `multi_taskmode` は **`mode='single_turn'`** を使う (`mode='task'` を避ける): 本 eval はバッチ実行で
> ユーザー応答が無く、task-mode は途中でユーザーへ chat 確認する可能性があり**ハング要因**になる。
> single_turn は「会話せず単発でタスクを完了する」モード。委譲ツール名は `{domain}_assistant` (sub 名
> そのもの、`request_task_*` ではない — ソース検証済み) で、AgentTool と同じく naming で対称に扱われる。

> `workflow_graph` の調整: 当初の「条件エッジ + JoinNode」構成は、JoinNode が全静的前任者の完了を待つため
> 条件スキップされたドメインで **deadlock** する (`_workflow.py` の `_requires_all_predecessors`)。
> よって条件選択を dispatcher (`ctx.run_node` 動的ディスパッチ、ADK 推奨) に移し、線形 spine で回避した。
> 委譲呼び出しが無いため record の `delegations` は空 — ルーティングは実ツール呼び出しのドメインで観測する。

## 構成

| パス | 役割 |
|---|---|
| `src/lab/model.py` | Gemini (global 固定 / temp=1.0 / thinking LOW) |
| `src/lab/naming.py` | ドメイン名・委譲名・skill メタの単一ソース (ADK 非依存)。採点と構築が共有 |
| `src/lab/environments.py` | CLEAN(6) / DISTINCT(12) / CONFUSABLE(18)。`tools_for_env` / `ordered_domains` / `shuffle_tools` |
| `src/lab/tools/` | mock ツール (bq=DuckDB, slack/billing/oncall/portal=JSON)。`_fixtures.load_fixture` で共有ロード |
| `src/lab/fixtures/` | 決定的 fixture (seed 固定・commit 済み。billing=SEED+2 / oncall=SEED+3 / portal=SEED+4) |
| `src/lab/variants/` | `single_flat` / `single_skills` / `multi_agenttool` / `multi_transfer` / `multi_taskmode` / `workflow_graph` + `common.py` |
| `eval/tasks.py` | 16 タスク (A/B/C/D/E) + `_compute_gt` (fixture から機械導出) + `score_record` |
| `eval/run_eval.py` | (variant,env,task,run) 直交ランナー + `MetricsPlugin` |
| `eval/report.py` | Wilson CI 集計 (group_field で cell 群化) + Markdown |
| `eval/rescore.py` | 保存済み結果のオフライン再採点 (cell 集計) |
| `scripts/gen_fixtures.py` | 決定的 fixture 生成 (seed=42) |
| `tests/` | fixture 健全性 + 採点器 (gaming/terse 両側) + バリアント構築 + naming |

## 実行方法

```bash
uv sync --frozen
uv run python scripts/gen_fixtures.py   # 決定的 fixture 再生成 (commit 済みと同一)
uv run pytest -q && uv run ruff check .  # オフライン検証 (Vertex 不要)

# クロス評価 (Vertex 接続。ADC + env 必要)。収集セル計画 13 セル (single_flat×3env + 他 5×2env)
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=<your-project>
uv run python eval/run_eval.py --smoke --tag _smoke        # V-1 smoke (13セル×A1/C1/E1×1run)
uv run python eval/run_eval.py --runs 8 --tag _main        # 本番 (13セル×16タスク×8run)
uv run python eval/run_eval.py --variants single_flat --envs clean --tasks B1 C1  # 絞り込み

# 採点器を修正した後の再採点 (完全オフライン・LLM 不要)。新 tag は _rescored も併せて commit
uv run python eval/rescore.py --tag _smoke
```

`.env.example` を `.env` にコピーして値を設定してもよい (`.env` は commit しない)。

## 較正と runs 設計

gemini-3-flash-preview は強く、多段導出でタスクを硬化しても CLEAN 単一 flat のベースラインは
天井 (probe で 16/16) に張り付く。よって本実験は**品質 (pass rate) の差だけに依存しない**設計にする:
CONFUSABLE 環境での劣化・トークンコスト差 (multi > single を probe で観測)・trajectory 指標
(trap_hit / trap_fatal / selection / delegations) で仮説を検証する。

**runs 設計 (ユーザー承認済みの縮退)**: temperature=1.0 (thinking モデルの公式推奨) で分散が大きい
ため本来は runs≥10 が望ましいが、コスト都合で**既定 runs=8 に縮退**する。Wilson 95% CI が割れる
(隣接セルと CI が重なって差を主張できない) セルに限り、事後に runs を 10 へ追い足して CI を締める。
raw record は append-only なので追い足しは既存結果を壊さない。

## 後続作業 (TODO)

- **本収集** — `--runs 8` で 13 セル × 16 タスクを実測し `eval/results/` に保存 (raw + `_rescored` 同時 commit)。
- **report.py の見出し** を agent-composition 用に更新 (現在は流用元「知識配置バリアント評価」のまま)。
- 天井が問題になる場合の追加硬化 (portal 罠の巧妙化など) は結果を見て判断。

## バージョン注記

- **`google-adk==2.4.0` を pin**。依存は `==` または lower-bound pin + `uv.lock` を commit
  (`uv sync --frozen` が通ること)。
- ローカルの `python3` が 3.11 未満でも、uv がプロジェクト用に Python 3.11+ を用意する。
