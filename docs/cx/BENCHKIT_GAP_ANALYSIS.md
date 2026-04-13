# BenchKit ギャップ分析 / BenchKit Gap Analysis

## 言語方針 / Language Policy

本書は日本語を正本とし、英語は参照用の補助訳とする。
解釈に差異がある場合は日本語版を優先する。

This document uses Japanese as the authoritative version.
The English text is provided as a supporting reference translation.
If any discrepancy exists, the Japanese version takes precedence.

## 1. 文書の位置づけ / Position of This Document

本書は [BENCHKIT_SPEC.md](./BENCHKIT_SPEC.md) を実装確認用の観点に落とし込んだ補助文書である。
目的は、BenchKit の主要機能について、

- 仕様上の要求
- 現状実装
- 不足している点
- 他機能との依存関係
- 実装優先度

を見える化することである。

This document is a companion to [BENCHKIT_SPEC.md](./BENCHKIT_SPEC.md), translating the specification into an implementation-facing checklist.
Its purpose is to make visible, for each major BenchKit function:

- specification requirements
- current implementation status
- missing parts
- dependencies with other functions
- implementation priority

## 2. 現状の要約 / Current Summary

BenchKit は現時点で、継続的ベンチマークの基盤部分はかなり整っている。
特に、

- shell-first の実行基盤
- system.csv 主導の CI ジョブ生成
- Result JSON への結果正規化
- 結果・推定結果・使用量のポータル表示
- 最上位アプリケーションのソース出自情報の基本追跡

はすでに実装されている。

一方で、継続的推定は入口があるものの横展開が不足しており、AI 駆動最適化連携はまだ接続点の段階にある。

BenchKit already has a solid foundation for continuous benchmarking, especially in:

- shell-first execution
- system.csv-driven CI job generation
- result normalization into Result JSON
- portal presentation of benchmark, estimation, and usage data
- basic source provenance tracking for the top-level application

Continuous estimation has now moved beyond a mere entry point: a common estimation flow, a `weakscaling` reference path, a detailed dummy package for `qws`, and result-provenance handoff have all been implemented.
However, estimation is still not yet broadly deployed across multiple applications, and AI-driven optimization integration remains mostly at the integration-point stage.

## 2.1 現時点で明示しておく設計負債 / Explicit Design Debts to Keep Visible

現時点では、単に未実装というより、「いったん方向は決めたが、まだ固定しきっていない」論点がいくつかある。
この節は、それらを後で見失わないための明示的なメモである。

- 推定 package / flow の境界:
  BenchKit 共通層と package 側の責務分担はかなり整理されたが、metadata discovery、複数 detailed package 間の一般化、package 間 compare の扱いはまだ固定していない。
- app 側の推定宣言 API:
  `estimate.sh` に current / future package と section 宣言を書く流れは見えてきたが、他 app へ横展開する前提の最終 API はまだ固めていない。
- 推定結果 compare UI:
  detail 画面で current / future breakdown、fallback、applicability は見えるようになったが、同一 `code/exp` 間の差分把握 UI はまだ後回しにしている。
- 結果 quality の扱い:
  portal 上の quality badge、detail view、latest-result current-state summary は実装済みだが、CI を fail させる validator にはしていない。品質評価は現在も visibility-first である。
- site capability checker:
  `/results/usage` に lightweight configuration checks は入ったが、CI 実行可否と直接結び付く自動 checker にはまだしていない。
- app/system coverage 判定:
  現在の coverage matrix は `list.csv` と `build.sh` / `run.sh` の structured shell-branch detection に基づくが、完全な execution-contract checker にはまだなっていない。

At the current stage, several issues are not simply "missing implementations" but rather intentionally deferred or not yet fully fixed as design boundaries.
This section keeps those visible so they are not forgotten later.

- estimation package / flow boundary:
  the separation between BenchKit common flow and package-owned behavior is much clearer now, but metadata discovery, generalization across multiple detailed packages, and package-level comparison are not yet fixed.
- application-side estimation declaration API:
  the direction of declaring current / future packages and section bindings in `estimate.sh` is becoming clear, but the final cross-application API is not yet frozen.
- estimation compare UI:
  detail views now expose current / future breakdown, fallback, and applicability, but same-`code`/`exp` comparison remains intentionally deferred.
- result quality handling:
  quality badges, detail views, and latest-result current-state summaries are implemented, but they are not yet enforced as CI-failing validation; the current approach remains visibility-first.
- site capability checker:
  `/results/usage` now has lightweight configuration checks, but there is still no automatic checker directly tied to CI execution readiness.
- app/system coverage evaluation:
  the current coverage matrix uses `list.csv` plus structured shell-branch detection in `build.sh` / `run.sh`, but it still stops short of a full execution-contract checker.

## 3. 機能別ギャップ分析 / Function-by-Function Gap Analysis

| 機能 | 仕様要求 | 現状実装 | 不足・課題 | 他機能への影響 | 優先度 |
|---|---|---|---|---|---|
| ベンチマーク実行定義 | アプリごとの build/run/list を保持し、継続実行可能であること | `programs/*` に `build.sh` `run.sh` `list.csv`、一部 `estimate.sh` がある | 追加や修正がまだ人手中心。雛形生成や申請導線がない | 申請・承認・AI 連携の前提になる | 高 |
| CI ジョブ生成 | system と queue 情報を使って CI 実行を生成すること | `matrix_generate.sh` と `job_functions.sh` が実装済み。`add-site.md` に `system.csv` / `queue.csv` / `system_info.csv` の責務分担、接続確認順序、障害切り分け、onboarding checklist も整理された。portal の `/results/usage` では queue 定義抜けや `system_info.csv` 未登録を軽く確認できる | site capability を CI に結び付けた自動 checker や、site ごとの capability summary は未実装 | 拠点追加、予算管理、申請フォームの自動化に影響 | 高 |
| 結果正規化 | `run.sh` 出力を Result JSON に正規化すること | `bk_emit_result`、`bk_emit_section`、`bk_emit_overlap`、`result.sh` が実装済み。portal 側では一覧の quality badge と詳細の `Quality` セクションで `source_info`、`fom_breakdown`、推定入力参照の有無を軽く確認でき、`/results/usage` では最新 result ベースの current-state も見られる | app ごとの差異を体系的に検証する validator や、履歴横断の quality 集計・基準化はまだ弱い | 推定、可視化、AI 診断の入力品質に直結 | 高 |
| 性能推定 | Result JSON から Estimate JSON を生成し、可視化可能であること | `scripts/estimation/common.sh`、`scripts/estimation/run.sh`、`scripts/result_server/send_estimate.sh`、`estimated` 画面あり。`qws` では `weakscaling` と詳細ダミー推定、section ごとの package 指定、補助データ参照、section-level fallback、requested/applied package 識別、top-level applicability end state、推定元 result と推定結果自体の UUID / timestamp 保持まで動作する | 横展開はまだ `qws` 中心。複数 detailed package の本実装、再推定比較運用、他 app への適用が未完成 | AI 駆動、将来機評価、継続的フィードバックの基盤になる | 最優先 |
| 推定結果表示 | Estimate JSON を一覧・詳細で表示できること | `result_server/routes/estimated.py` とテンプレートが実装済み。requested/applied package、applicability、estimate UUID の基本表示に加えて、HTML detail で current / future breakdown、section / overlap 単位の fallback / package applicability まで表示できる。home からの導線も整理済みで、未認証時は login required であることも入口で分かる | compare UI、`not_applicable` の説明補助、複数 estimate 間の差分把握はまだ弱い | 推定運用を本格化すると重要度が上がる | 高 |
| 使用量集計 | 実行使用量を集計し、運用判断に使えること | `node_hours.py` と `/results/usage` が実装済み。node-hour 集計に加えて、登録済み system と app の対応状況を `list.csv` および `build.sh` / `run.sh` の検出に基づく coverage matrix で確認できる。さらに `system.csv` / `queue.csv` / `system_info.csv` の軽い診断、partial support、最新 result ベースの quality / source tracking current-state も表示できる | 予算主体、アカウント主体、runner 主体との結び付きや、site capability の自動 checker はまだ弱い | 多拠点運用と予算管理の核になる | 高 |
| ソース出自情報 | 最上位アプリケーションの commit hash を追跡すること | `bk_fetch_source` と `source_info` が実装済み。portal 側でも `/results/usage` に最新 result ベースの `source_status`、`source_type`、`source_reference`、不足 field が出せる | すべての app で徹底されていない。 archive/file の場合は commit hash を持てない | 推定比較、AI 最適化、回帰分析の再現性に直結 | 高 |
| 拠点接続 | runner, scheduler, queue, site 条件を扱えること | `system.csv` と CI 生成が連携済み。`system_info.csv` を含めた責務分担、接続確認手順、障害切り分け、site onboarding checklist が docs に整理済みで、portal 側でも軽い configuration checks が見える | docs 依存がまだ強く、自動 checker や site ごとの capability summary は未実装 | 使用量集計、申請、runner 分散運用に直結 | 高 |
| 認証・権限 | 結果・管理機能へのアクセス制御を行うこと | TOTP、admin、閲覧制御あり | 申請者、拠点担当者、推定モデル管理者などの役割分化が未定義 | 申請・承認・AI 指示導入時に重要になる | 中 |
| shell-first 共通化 | shell を保ったまま共通処理を吸収すること | `bk_emit_*` と `bk_fetch_source` は導入済み | build/run テンプレート化、scaffold、部分生成の仕組みがない | app 追加の敷居を下げ、推定横展開も楽にする | 高 |
| 申請・承認・自動PR | ポータルから変更要求を受け、承認後に Git へ落とせること | 構想のみ | 未実装 | app 追加、条件変更、推定モデル変更の運用負荷を大きく下げる | 高 |
| AI 駆動最適化連携 | AI が最適化提案や変更提案に参加できること | 構想のみ | 対象データ、承認フロー、評価指標、再実行ループが未定義 | 推定が先に固まるほど設計しやすくなる | 高 |
| MCP 連携 | 外部エージェントやツールが制御された形で情報取得・操作できること | 構想のみ | read-only から始める API / ツール設計が未着手 | AI 連携、ポータル連携、外部ツール連携の共通面になる | 中 |

## 4. 相互依存と順序効果 / Dependencies and Sequencing Effects

### 4.1 性能推定を先に固める効果 / Why Estimation Should Come First

性能推定は、単独の 1 機能ではなく、以下の複数機能の接続点になっている。

- Result JSON の品質
- source_info の品質
- Exp や FOM breakdown の意味付け
- 結果ポータルでの表示粒度
- 将来機比較やスケーリング比較のモデル化
- AI に渡す評価関数や目的関数

したがって、性能推定の仕様が固まると、

- AI 駆動最適化で何を最適化対象にするかが明確になる
- 結果正規化で何を必須項目にすべきかが明確になる
- 申請フォームでどこまで利用者が修正可能かが明確になる
- 使用量集計や運用上の優先順位付けにも、推定価値を反映しやすくなる

Estimation is not an isolated function. It is a junction point for:

- Result JSON quality
- source_info quality
- the semantics of Exp and FOM breakdown
- how the portal presents model assumptions
- future-system and scaling comparisons
- the objective functions given to AI-driven optimization

Once the estimation specification is clarified, many other design decisions become easier.

### 4.2 ある改善が別の機能を強くする例 / Examples Where One Improvement Enables Another

#### A. 結果正規化の強化 -> 推定と AI の両方が強くなる

`bk_emit_*` と Result JSON の標準化が進むほど、

- 推定モデルは app ごとの差異を吸収しやすくなる
- AI は入力データの揺れに悩まされにくくなる
- ポータル表示も共通化しやすくなる

#### B. source_info の徹底 -> 推定比較と AI 最適化が意味を持つ

最上位アプリケーションの commit hash が確実に取れていないと、

- 推定結果の比較
- 回帰検知
- AI が提案した変更の効果確認

が弱くなる。

#### C. 拠点接続の整理 -> 使用量集計と分散 runner 運用が実用化される

拠点接続が暗黙知のままだと、

- 予算主体ごとの集計
- site owner ごとの管理
- 分散 runner への委譲

が曖昧になる。

### 4.3 ある改善が別の機能を不要化または縮小する例 / Examples Where One Improvement Shrinks Another Need

#### A. shell-first 共通化が進むと、YAML の表現力を過度に増やす必要が減る

`build.sh` / `run.sh` の共通関数や scaffold が整うほど、複雑な YAML DSL を導入する必要は小さくなる。

#### B. 申請・承認・自動PR が整うと、アプリ開発者に直接 repo 編集を求める運用は縮小できる

これは app 追加や条件変更の敷居を大きく下げる。

#### C. 推定仕様が固まると、AI 駆動 PoC の探索範囲が絞られる

推定が曖昧なままだと AI 側の PoC は評価関数を定めにくい。
逆に推定仕様が固まると、AI 側は「何を改善成功とみなすか」を定めやすくなる。

## 5. 最優先で詰めるべき領域 / Highest-Priority Areas

### 5.1 最優先: 性能推定機能 / Top Priority: Performance Estimation

性能推定機能は最優先で仕様を確定し、設計・実装を進めるべきである。

最低限、以下を詰める必要がある。

- Estimate JSON の必須項目と意味
- 現在機と将来機の比較モデル
- benchmark 側のどの結果を推定入力に使うか
- Exp の扱い
- FOM breakdown をどこまで推定対象にするか
- 推定モデルの種別と識別方法
- 再推定のトリガ、履歴、比較可能性と表示導線

現状は `qws` が先行 app として、

- `weakscaling`
- `instrumented_app_sections_dummy`
- 推定元 result の UUID / timestamp 引き回し
- side ごとの `model` 表現

まで動作確認済みである。
したがって、入口確認段階はすでに超えており、次はこの形を複数 app に横展開できるよう引き上げる必要がある。

#### 5.1.1 推定機構の実装 GAP 再調査 / Re-Survey of Estimation Implementation Gaps

現時点の推定実装は、仕様に対して次の状態にある。

| 項目 | 仕様上の期待 | 現状実装 | GAP | 優先度 |
|---|---|---|---|---|
| 共通推定エントリ | app 側 `estimate.sh` を薄くし、共通呼び出し順を持つこと | `scripts/estimation/common.sh` と package 呼び出し型の `qws/estimate.sh` がある | 他 app への横展開が未着手。`estimate.sh` 内の宣言ブロックの共通 API も未固定 | 最優先 |
| `weakscaling` package | section ごとの時間を app 側が出し、`identity` と `logp` で weak scaling を構成できること | `weakscaling` を実装済み。`identity` / `logp` を current 側で適用し、unsupported な section package は fallback できる | 他 app への横展開と、より明示的な package discovery は未完 | 高 |
| 適用可能性判定 | 不足入力を `applicable/fallback/not_applicable/needs_remeasurement` で扱うこと | `weakscaling` と `instrumented_app_sections_dummy` でこれらを扱える。Estimate JSON でも requested / applied package、fallback、`applicable` / `partially_applicable` / `fallback` / `not_applicable` を表現でき、estimated detail でも section / overlap 単位に表示できる | 複数 detailed package 間の分岐、より細かい fallback 選択、compare UI 側の見せ方は未実装 | 高 |
| package metadata | package 名、版、required inputs、fallback policy を持つこと | `weakscaling` / 詳細ダミーとも最小 metadata を持つ。`weakscaling` の `method_class` は `minimum` に整理された | richer metadata を discovery や UI に活かす実装がまだ無い | 中 |
| section ごとの package 指定 | 区間ごとに推定 package を割り当てられること | `bk_emit_section` / `bk_emit_overlap` から Result JSON に `estimation_package` を載せられ、`instrumented_app_sections_dummy` でも dispatch に利用している。`weakscaling` では unsupported package を fallback する | 他 app への横展開と package discovery の整理が未完 | 最優先 |
| app 側推定宣言 | app 側が実行前に section / overlap と `estimation_package` をまとめて宣言できること | `qws/estimate.sh` で current / future package、target system / nodes、future 側 section / overlap 宣言を持てる | 宣言 API の更なる標準化、既定値の与え方、他 app への横展開は未完 | 最優先 |
| 追加採取実行 | 通常実行と別に詳細推定入力の採取だけを共通入口から追加実行できること | `bk_run_estimation_data_collection` 方向は整理済み | shell API、分岐条件、保存処理との接続は未実装 | 最優先 |
| section ごとの補助データ参照 | tgz 等の補助データを section ごとに紐付けられること | `qws` では section / overlap ごとに `artifacts` を Result JSON に保持し、詳細ダミー package でも利用している | 他 app への横展開と artifact 収集方式の一般化が未着手 | 高 |
| overlap 推定 | overlap を独立した推定部品として扱えること | Result JSON で保持でき、詳細ダミー package でも overlap の `bench_time/time` は扱える | overlap 専用 package や複数方式切替は未実装 | 中 |
| 詳細推定 package | `instrumented_app_sections` など取得方式別 package を持てること | `instrumented_app_sections_dummy` を `qws` 向け参照実装として実装済み | 実測区間時間や外部ツール区間時間を使う本格 package は未実装 | 最優先 |
| 複合推定 | section ごとに異なる方式を合成できること | `qws` と `instrumented_app_sections_dummy` で section ごとの package 指定、artifact 参照、section package dispatch、section-level fallback を実装済み | 複数実アプリへの適用、本格 package 実装、より一般的な合成規則は未着手 | 高 |
| 推定 provenance | 推定元 result と推定結果自体の出自情報を保持すること | 推定元 result の UUID / timestamp、requested/applied package、推定結果自体の UUID / timestamp を Estimate JSON に保持できる。result JSON 側にも server UUID / timestamp を保持できる | compare UI や再推定導線での活用は未整理 | 中 |
| 再推定 | `estimate_result_uuid` 起点で再推定し比較可能にすること | 再推定専用 trigger、child pipeline、result / estimate / estimation input の再取得、`reestimation` ブロック付与、CI 上での保存完了まで動作する | compare UI、portal からの起動導線、表示上の差分把握が未完 | 高 |
| 推定結果表示 | model / assumptions / applicability を表示できること | estimated 画面で requested/applied package、applicability、estimate UUID などの基本表示に加えて、detail 画面で current / future breakdown と section / overlap 単位の fallback / applicability を表示できる | 比較表示、`not_applicable` の説明補助、再推定との横並び表示は未整備 | 中 |

この表から、現在の最小核は以下と整理できる。

1. `scripts/estimation/common.sh` を中心とした共通呼び出しと Estimate JSON 出力
2. `weakscaling` による `identity` / `logp` ベースの最小推定経路
3. `instrumented_app_sections_dummy` による区間時間ベース詳細ダミー推定
4. 推定元 result UUID / timestamp の引き回し

逆に、まだ核ではないが後で効くものは以下である。

- 再推定比較 UI
- portal からの再推定要求フロー
- 複合推定の本格化
- counter / trace / overlap の本格活用
- compare を含む推定差分 UI 表示

#### 5.1.2 次の実装順 / Recommended Immediate Order

推定機構について、次の実装順を推奨する。

1. `qws` 以外の app へ推定方式を横展開する
2. `not_applicable` と compare を含む推定差分 UI を portal で見やすくする
3. 複数 detailed package 間の fallback と discovery を整理する
4. その後に再推定比較 UI と portal 起動導線へ進む

ここでいう区間時間ダミー package は、すでに最初の参照実装として導入済みである。
今後は、少なくとも以下を満たす方向へ育てる必要がある。

- `instrumented_app_sections` 型である
- section / overlap を入力として受け取る
- section ごとに package を割り当てられる将来拡張を阻害しない
- `bench_time` と `time` を区別して保持する
- `artifacts` が無くても動くが、あっても破綻しない

これにより、`weakscaling` と詳細推定の最初の 2 本柱は揃った。
そのうえで今後は、counter-based や trace-based package、section-level binding、推定結果 provenance へ進むのが自然である。

### 5.2 次点: AI 駆動最適化連携 / Next Priority: AI-Driven Optimization

AI 駆動最適化連携は、PoC を含む試行錯誤を前提として早めに始めてよい。
ただし、その前提として以下が必要になる。

- 何を最適化対象とするか
- 何を成功指標とするか
- どの commit と結果を結び付けるか
- どこまで自動変更を許すか
- 誰が承認するか

このうち、成功指標と比較対象の設計は性能推定と強く依存する。

## 6. 推奨する実装順序 / Recommended Order of Implementation

### 6.1 短期 / Short Term

1. `estimate.sh` の宣言ブロックと共通補助を整える
2. `bk_run_estimation_data_collection` の共通入口を整える
3. `qws` 以外に 1 から 2 本の app へ推定を横展開する
4. Estimate JSON と portal 表示を section / overlap 詳細まで整える
5. 再推定比較の UI / API を整える
6. package metadata discovery を portal や比較導線に活かす

### 6.2 中期 / Mid Term

1. 拠点接続の onboarding / validation を仕様化する
2. 使用量集計に予算主体・runner 主体の概念を入れる
3. app 追加と条件変更の申請・承認フローを設計する
4. shell-first な雛形を整える

### 6.3 並行 PoC / Parallel PoC

1. AI 駆動最適化の最小 PoC を設計する
2. read-only MCP のユースケースを絞る
3. 推定結果を AI へ渡す入出力形式を試す

## 7. 次に作るべき下位仕様 / Next Lower-Level Specifications

性能推定機能を最優先とするなら、次に必要なのは以下である。

1. `ESTIMATION_SPEC.md`
2. `ESTIMATE_JSON_SPEC.md`
3. `ESTIMATION_PACKAGE_SPEC.md`
4. `REESTIMATION_SPEC.md`
5. `RESULT_STORAGE_DESIGN.md`

If performance estimation is the top priority, the next documents to write should be:

1. `ESTIMATION_SPEC.md`
2. `ESTIMATE_JSON_SPEC.md`
3. `ESTIMATION_PACKAGE_SPEC.md`
4. `REESTIMATION_SPEC.md`
5. `RESULT_STORAGE_DESIGN.md`
