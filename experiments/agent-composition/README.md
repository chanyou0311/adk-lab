# agent-composition

Google ADK (Python) エージェントで、**単一の LLM エージェントと multi-agent 構成 (agent
composition) を統制比較する**実験 ([adk-lab](../../README.md) の実験のひとつ)。

> **状態: WIP (scaffold のみ)。** 実験ハーネス (モデル設定・計測 Plugin・mock ツール・
> 決定的 fixture・採点/集計/再採点の骨格) は用意したが、バリアント実装・タスク定義・
> fixture 拡張・smoke はまだ入っていない (後続作業)。

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
| 1 | 正答率 (quality) | タスク別 pass rate + Wilson 95% CI |
| 2 | トークンコスト | 総トークン + 内訳 (prompt / candidates / **thoughts** / tool-use-prompt / cached) |
| 3 | ルーティング精度 | 呼ばれた tool family (bq/slack) が expected と一致した割合 |
| 4 | 過剰拒否 (refusal) | 能力を「持たない」と誤って拒否した割合 |
| 5 | レイテンシ・LLM 呼び出し数 | ジョブ毎の壁時計時間と LLM 呼び出し回数 |
| 6 | thought signature 健全性 | function_call part の thought_signature 欠落数 / 起因の 400 発生 |

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
- `signature_missing_count` (送信 contents 中の function_call part で thought_signature が欠落した数)
- `signature_400` (thought_signature 起因の 400 でジョブが失敗したか)

streaming の partial レスポンスは usage が二重に来るため、`after_model_callback` の冒頭で
`partial` をガードしてトークンの二重計上を防ぐ。

## ハーネス構成 (scaffold)

| パス | 役割 | 状態 |
|---|---|---|
| `src/lab/model.py` | Gemini (global 固定 / temp=1.0 / thinking LOW) | ✅ |
| `src/lab/tools/` | mock ツール (bq=DuckDB in-memory, slack=JSON fixture) | ✅ (knowledge-placement から流用) |
| `src/lab/knowledge.py` | ドメイン知識の単一定義 (K1–K8) | ✅ (流用。ドメイン拡張は後続) |
| `src/lab/fixtures/` | 決定的 fixture (seed 固定・commit 済み) | ✅ (byte 一致で流用) |
| `src/lab/variants/common.py` | 共通 instruction 部品 (PERSONA / OPEN_MANDATE / ROUTING_GUIDANCE …) | ✅ |
| `src/lab/variants/__init__.py` | バリアントレジストリ `VARIANTS` | ⬚ 空 (後続) |
| `eval/tasks.py` | Task dataclass・score_record・汎用判定ヘルパー | ✅ 骨格 (TASKS は空) |
| `eval/run_eval.py` | クロス評価ランナー + `MetricsPlugin` (Gemini 3 計測拡張) | ✅ |
| `eval/report.py` | Wilson CI 集計 + Markdown レポート | ✅ 流用 |
| `eval/rescore.py` | 保存済み結果のオフライン再採点 | ✅ 流用 |
| `scripts/gen_fixtures.py` | 決定的 fixture 生成 (seed=42) | ✅ 流用 |
| `tests/` | fixture 健全性 + 採点ヘルパー回帰テスト | ✅ (汎用分のみ) |

## 実行方法

```bash
uv sync --frozen

# 決定的 fixture を生成 (seed=42、生成物は commit 済み。再生成しても同一)
uv run python scripts/gen_fixtures.py

# fixture と GT の健全性テスト・採点ヘルパー回帰テスト (Vertex 不要)
uv run pytest -q
uv run ruff check .

# クロスバリアント eval (Vertex に接続する。ADC + 下記 env が必要)
# NOTE: バリアント・タスク追加までは 0 cell。
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=<your-project>
uv run python eval/run_eval.py --runs 8

# 採点器を修正した後の再採点 (完全オフライン・LLM 不要)
uv run python eval/rescore.py --tag _main
```

`.env.example` を `.env` にコピーして値を設定してもよい (`.env` は commit しない)。

## 後続作業 (TODO)

1. **fixture 拡張** — agent composition の紛らわしさを引き出すドメイン/ツールの追加
   (独立 RNG `random.Random(SEED + n)` で既存 fixture をバイト不変に保つ)。
2. **タスク設計** — 単一 vs 分割で差が出るタスク群と、その決定的採点器 + GT を `eval/tasks.py` に追加。
3. **バリアント実装** — 単一エージェント (全ツール) / 役割分割 (AgentTool) など構成バリアントを
   `src/lab/variants/` に追加し `VARIANTS` へ登録。
4. **smoke → 本番 eval** — 小規模 smoke で健全性を確認後、runs≥8 で本番計測し `eval/results/` に保存
   (raw record 全量 + `_rescored` を同時 commit)。

## バージョン注記

- **`google-adk==2.4.0` を pin**。依存は `==` / lower-bound pin + `uv.lock` を commit
  (`uv sync --frozen` が通ること)。
- ローカルの `python3` が 3.11 未満でも、uv がプロジェクト用に Python 3.11+ を用意する。
