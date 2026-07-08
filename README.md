# adk-thin-agent-lab

Google ADK (Python) エージェントで **ドメイン知識をどこに置くと、root instruction を薄く保ちつつ
タスク品質を維持できるか** を定量比較する実験ハーネス。

同一の知識・タスク・モデルのまま、**知識の「置き場所」だけを変えた 6 バリアント**を作り、
14 タスク × N runs をクロスバリアントで走らせて、正答率 (Wilson 95% CI)・トークン・レイテンシ・
ツールルーティング精度・拒否率を決定的に採点する。結果はブログ記事の素材になる。

## 設計マトリクス (6 バリアント)

知識の中身は `src/lab/knowledge.py` の単一定義 (K1–K6)。バリアント間で変えるのは配置だけ。

| variant | root instruction | tools | 知識の所在 |
|---|---|---|---|
| `fat_closed` | PERSONA + 閉じた列挙 + 知識全文 | bq+slack (rich=False) | root |
| `fat_open`   | PERSONA + 開いた mandate + 知識全文 | bq+slack (rich=False) | root |
| `thin_none`  | PERSONA + 開いた mandate | bq+slack (rich=False) | **なし** (下限対照) |
| `tool_desc`  | PERSONA + 開いた mandate | bq+slack (**rich=True**) | tool docstring |
| `subagents`  | PERSONA + 開いた mandate + ルーティング指針 | AgentTool(data_analyst / comms_analyst) のみ | sub-agent instruction |
| `skills`     | PERSONA + 開いた mandate | bq+slack (rich=False) + SkillToolset | SKILL 本文 (L2) |

- **mandate の開閉** (`fat_closed` vs `fat_open`) と **知識配置** は別変数。交絡を避けるため両者を分離した。
  - 開いた mandate = 「ツールは *取得*、分析・要約・予測は *エージェント自身の仕事*」を明示 (fumo-adk の
    過剰拒否対策 B 案を一般化)。閉じた列挙 = ツール用途を並べるだけ。
- 全バリアントで **ツール (bq+slack) は常時露出**。`skills` でもツールゲーティングはしない
  (知識配置だけを変える統制のため)。

## ドメイン知識 (K1–K6)

シナリオ: 架空のオンラインストア (2026-06)。6/24 に v2.4.0 デプロイ → INC-42 (チェックアウト決済障害) →
6/24–26 売上落ち込み → 6/26 ロールバックで解消。INC-43 (sev1 未解決)・INC-44 (sev2 未解決) が判別用。

- **sales-analytics**: K1 売上集計は `is_test=true` を除外 / K2 純売上 = amount ÷ 1.1 (税抜) / K3 `cancelled` は除外
- **slack-ops**: K4 障害の正式情報源は #alerts の `[INC-n]`、クローズ報なし=未解決 / K5 sev1=顧客影響・sev2=内部のみ /
  K6 リリースは #releases、苦情は #support

## 14 タスク (`eval/tasks.py`)

| cat | 例 | 判別する力 |
|---|---|---|
| A | 売上合計 / 最新障害 / カラム構成 | 単一ツールの基本的な取得・集計 |
| B | 落ち込み確認+原因調査 / INC の影響定量化 | クロスドメイン (bq×slack) の統合 |
| C | 7月売上予測 / トレンド分析 / 反実仮想 | 分析・予測 (拒否プローブ) |
| D | churn rate とは / WHERE と HAVING | ツール不要の一般知識 (過剰ツール検出) |
| E | 純売上 (税抜) / 顧客影響の未解決障害 | 知識依存 (K2 / K4+K5 が無いと解けない) |

ground truth は fixtures への DuckDB クエリで**採点時に計算** (ハードコードしない)。数値照合は
`answer_contains_number` (万/億・カンマ対応, 相対誤差 1%)、日付は表記ゆらぎ吸収、拒否は
`REFUSAL_PATTERNS` で検出する。

## モデル

Vertex AI の `gemini-3-flash-preview`。**global エンドポイント限定** (regional は 404) なので
`src/lab/model.py` の `_GlobalGemini` (fumo-adk 由来) で api_client の location を global に固定する。
全 LlmAgent を `temperature=0` で走らせる。

## 計測方法 (重要)

トークンと tool 呼び出しは ADK の **Plugin** (`after_model_callback` / `before_tool_callback`) で収集する。
ADK 2.4.0 の `AgentTool` は sub-agent を**別 Runner で実行**するため、sub-agent 内部の LLM 呼び出し・
tool 呼び出しは親の event ストリームには現れない。Plugin は AgentTool 経由で子 Runner に伝播するので、
`subagents` バリアントでも root+sub 横断でトークンと trajectory を漏れなく数えられる (これが唯一の
横断計測手段)。ツール family は `bq_`/`slack_` prefix と sub-agent 名の別名 (data_analyst→bq,
comms_analyst→slack) から判定し、skill 系ツール (list_skills/load_skill…) は routing 判定で無視する。

## 実行方法

```bash
uv sync

# 決定的 fixture を生成 (seed=42、生成物は commit 済み。再生成しても同一)
uv run python scripts/gen_fixtures.py

# fixture と GT の健全性テスト (Vertex 不要)
uv run pytest -q
uv run ruff check .

# クロスバリアント eval (Vertex に接続する。ADC + 下記 env が必要)
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=<your-project>
uv run python eval/run_eval.py                       # 全 6 variants × 14 tasks × runs=10
uv run python eval/run_eval.py \
  --variants fat_closed thin_none skills \
  --tasks A1 A3 D1 E2 --runs 1 --tag _smoke          # スモーク (小規模)

# 静的コスト計測 (instruction / tool 宣言のトークン量)
uv run python eval/static_metrics.py
```

`.env.example` を `.env` にコピーして値を設定してもよい (`.env` は commit しない)。

## 出力 (`eval/results/`)

- `results{tag}.json` — 全 raw record (final_text 全文・tool trajectory・トークン・レイテンシ)
- `RESULTS{tag}.md` — variant×category の pass rate + Wilson 95% CI + トークン/レイテンシ + route ok 率 + 拒否率
- `static_metrics.json` / `STATIC_METRICS.md` — バリアント別の固定コンテキストトークン量

## バージョン注記・既知の制約

- **`google-adk==2.4.0` を pin**。`SkillToolset` / `google.adk.skills` は **Experimental** で API が変動しうる
  (本ハーネスは inline の `models.Skill` を構築して渡す方式)。`FeatureName.JSON_SCHEMA_FOR_FUNC_DECL`
  有効化の UserWarning が出るが無害。
- `skills` の静的計測は「毎リクエスト注入される SkillToolset の定型 system instruction (boilerplate)」を
  固定層として計上し、`<available_skills>` XML (L1) は **オンデマンド列** として別掲する (ADK 2.4.0 は
  list_skills ツールがある限り L1 XML を system instruction に注入しない)。load_skill 時の L2 本文と
  発見往復の実行時コストは `RESULTS.md` の実測トークンに現れる。
- ローカルの `python3` が 3.11 未満でも、uv がプロジェクト用に Python 3.11+ を用意する。
