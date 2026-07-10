# agent-composition 評価 — 統合レポート (canonical)

ブログ記事 (https://blog.fumo.jp/posts/adk-agent-composition-patterns/) の数値の正本。
`uv run python eval/canonical_report.py` でいつでも決定的に再生成できる (raw record は
append-only、本ファイルは派生成果物)。

- model: `gemini-3-flash-preview` (`google-adk==2.4.0`)  ·  runs/(cell,task): 8 (C カテゴリのみ追い足し込み n=64/構成)
- 供給元: `results_main_rescored.json` + `results_main2_rescored.json` (multi_taskmode のみ) + `results_graph2_rescored.json` + `results_ctopup_rescored.json`
- マージ規則: `_main2` の workflow_graph 2 セルは planner 修正前の旧実装のため除外し `_graph2` が supersede。`_ctopup` は C 列と裏付け数値のみに合流し、pass 総合とコスト分布には混ぜない
- 収集条件差: `_main` (flat/skills/agenttool/transfer) は LLM 呼び出し無制限、`_main2`/`_graph2`/`_ctopup` (taskmode/graph/C 追い足し) は暴走発見後の cap=120。cap 到達 record は error として pass 分母から除外 (本レポートの母集団で 6 件)。無制限の `_main` で 120 超は 7/1152 件・全て E (詳細は README)
- 集計対象は scored record のみ (エージェント挙動起因の失敗は passed=False で含め、インフラ起因エラーのみ除外 — report.is_scored)

## 記事スコアボード (CONFUSABLE)

median/p95 tok は E (答えの存在しない質問) を除く — E の探索暴走が分布を桁単位で歪めるため。暴走込みの期待コストは mean tok (E 込み) 列を見る。

| 構成 | pass (95% CI) | C 罠 (95% CI, n) | D | E | median tok (E 除く) | p95 tok (E 除く) | mean tok (E 込み) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `single_flat` | 97% [92%–99%] | 89% [79%–95%] (n=64) | 100% | 94% | 5.9k | 17.4k | 13.1k |
| `multi_transfer` | 93% [87%–96%] | 75% [63%–84%] (n=64) | 100% | 94% | 7.6k | 13.5k | 7.7k |
| `multi_agenttool` | 92% [86%–96%] | 73% [62%–83%] (n=64) | 100% | 94% | 7.5k | 20.8k | 16.7k |
| `single_skills` | 91% [84%–95%] | 75% [63%–84%] (n=64) | 100% | 81% | 10.6k | 23.5k | 16.9k |
| `multi_taskmode` | 88% [81%–93%] | 68% [56%–78%] (n=63) | 100% | 79% | 7.8k | 22.7k | 25.6k |
| `workflow_graph` | 75% [67%–82%] | 61% [49%–72%] (n=64) | 38% | 100% | 6.9k | 38.0k | 27.0k |

## 発見の裏付け数値

### C3 (データカタログ罠) の自己回復 — confusable、base+追い足し

| variant | passed / n |
| --- | --- |
| `multi_agenttool` | 0/16 |
| `multi_taskmode` | 0/16 |
| `multi_transfer` | 0/16 |
| `single_flat` | 10/16 |
| `single_skills` | 0/16 |
| `workflow_graph` | 1/16 |

### trap_fatal (C カテゴリで罠を踏んだまま終了) — confusable、base+追い足し

| variant | trap_fatal / n |
| --- | --- |
| `multi_agenttool` | 16/64 |
| `multi_taskmode` | 19/63 |
| `multi_transfer` | 16/64 |
| `single_flat` | 7/64 |
| `single_skills` | 16/64 |
| `workflow_graph` | 25/64 |

### E カテゴリ (irrelevance) の mean tokens — 探索暴走の env 依存

| variant | env | mean tokens |
| --- | --- | --- |
| `multi_agenttool` | clean | 14,568 |
| `multi_agenttool` | confusable | 75,349 |
| `multi_taskmode` | clean | 25,275 |
| `multi_taskmode` | confusable | 82,592 |
| `multi_transfer` | clean | 8,108 |
| `multi_transfer` | confusable | 7,578 |
| `single_flat` | clean | 1,085,850 |
| `single_flat` | confusable | 50,520 |
| `single_flat` | distinct | 354,067 |
| `single_skills` | clean | 30,606 |
| `single_skills` | confusable | 45,780 |
| `workflow_graph` | clean | 1,402 |
| `workflow_graph` | confusable | 4,340 |

## セル別サマリ (13 セル)

| cell | pass (95% CI) | route ok | refusal | mean tokens | latency(s) | errors |
| --- | --- | --- | --- | --- | --- | --- |
| `multi_agenttool@clean` | 97% [92%–99%] | 90% | 0% | 7,704 | 16.4 | 0 |
| `multi_agenttool@confusable` | 92% [86%–96%] | 71% | 0% | 16,673 | 20.4 | 0 |
| `multi_taskmode@clean` | 98% [94%–100%] | 90% | 0% | 10,532 | 16.2 | 0 |
| `multi_taskmode@confusable` | 88% [81%–93%] | 73% | 0% | 25,558 | 19.5 | 2 |
| `multi_transfer@clean` | 98% [94%–100%] | 91% | 0% | 7,660 | 9.7 | 0 |
| `multi_transfer@confusable` | 93% [87%–96%] | 71% | 0% | 7,744 | 9.8 | 0 |
| `single_flat@clean` | 98% [93%–99%] | 84% | 0% | 140,815 | 23.2 | 0 |
| `single_flat@confusable` | 97% [92%–99%] | 48% | 0% | 13,133 | 9.6 | 0 |
| `single_flat@distinct` | 96% [91%–98%] | 77% | 0% | 48,974 | 12.8 | 0 |
| `single_skills@clean` | 98% [93%–99%] | 88% | 0% | 14,231 | 12.0 | 0 |
| `single_skills@confusable` | 91% [84%–95%] | 77% | 0% | 16,911 | 12.2 | 0 |
| `workflow_graph@clean` | 80% [73%–86%] | 100% | 2% | 8,852 | 14.4 | 0 |
| `workflow_graph@confusable` | 75% [67%–82%] | 70% | 0% | 26,995 | 18.4 | 3 |
