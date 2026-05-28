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

本書でいう GAP は、`BENCHKIT_SPEC.md` で求めている機能・運用能力に対する未実装、未接続、未固定の部分に限定する。
テスト数、対応アプリ数、品質スコア、coverage 率などの量・品質指標は、SPEC が明示的な閾値やゲートを要求している場合を除き、それ自体を GAP とは扱わない。
それらは現状把握や優先度判断の補助情報として扱う。

This document is a companion to [BENCHKIT_SPEC.md](./BENCHKIT_SPEC.md), translating the specification into an implementation-facing checklist.
Its purpose is to make visible, for each major BenchKit function:

- specification requirements
- current implementation status
- missing parts
- dependencies with other functions
- implementation priority

In this document, a gap means an unimplemented, unconnected, or unsettled part of a function or operating capability required by `BENCHKIT_SPEC.md`.
Counts and quality indicators, such as the number of tests, number of supported applications, quality scores, or coverage rates, are not treated as gaps unless the SPEC explicitly defines them as thresholds or gates.
They are used only as supporting context for understanding the current state and prioritization.

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

As of the current repository survey, BenchKit has multiple benchmark applications with `build.sh`/`run.sh`, while `qws` is still the only application with an `estimate.sh`.
The result portal also already has a meaningful pytest-based test suite under `result_server/tests`, and the repository now has a repo-local Python dependency manifest, a standard portal test entrypoint under `result_server/tests`, and a lightweight GitHub Actions verification path for portal-oriented changes.
The main GitLab pipeline still intentionally skips heavy benchmark execution when a direct or manually triggered GitLab pipeline sees changes limited to `result_server/**/*` or portal display metadata such as `config/system_info.csv`. Protected-branch synchronization itself uses `ci.skip`, so the dedicated lightweight GitHub Actions path should continue to be kept in sync as portal-side files evolve.

## 2.1 現時点で明示しておく設計負債 / Explicit Design Debts to Keep Visible

現時点では、単に未実装というより、「いったん方向は決めたが、まだ固定しきっていない」論点がいくつかある。
この節は、それらを後で見失わないための明示的なメモである。

- 推定 package / flow の境界:
  BenchKit 共通層と package 側の責務分担はかなり整理されたが、metadata discovery、複数 detailed package 間の一般化、package 間 compare の扱いはまだ固定していない。
- app 側の推定宣言 API:
  `estimate.sh` に current / future package と section 宣言を書く流れは見えてきたが、他 app へ横展開する前提の最終 API はまだ固めていない。
- 推定結果 compare UI:
  detail 画面で current / future breakdown、fallback、applicability は見えるようになったが、同一 `code/exp` 間の差分把握 UI はまだ後回しにしている。
- 結果品質サマリの扱い:
  SPEC は portal 上の品質サマリ表示を求めているが、品質スコアの閾値や PR gate は定義していない。そのため、quality badge、detail view、latest-result current-state summary は内部管理・visibility-first の表示機能として扱い、量・品質の不足そのものを GAP とはしない。
- site capability checker:
  `/results/usage` の lightweight configuration checks のうち、公開 `system_info.csv` が `system.csv` / `queue.csv` に対応していることは CI preflight へ昇格済みである。一方、app support matrix はアプリごとの準備状況差が大きいため、現時点では CI failure にせず portal visibility に留める。
- app/system capability visibility:
  現在の coverage matrix は `list.csv` と `build.sh` / `run.sh` の structured shell-branch detection に基づくが、完全な execution-contract checker にはしていない。これは未実装というより、現段階では gate 化しない運用判断である。GAP として扱うのは、SPEC 上必要な site onboarding や運用判断に必要な capability summary / validation が未接続な部分に限る。
- result portal の検証導線:
  repo-local な Python 依存関係定義、標準の test entrypoint、portal-oriented 変更時に走る lightweight CI は固定済みである。一方で、upload helper や portal 表示メタデータなど portal 周辺の対象が増えるたびに path filter を追従させる必要は残る。

At the current stage, several issues are not simply "missing implementations" but rather intentionally deferred or not yet fully fixed as design boundaries.
This section keeps those visible so they are not forgotten later.

- estimation package / flow boundary:
  the separation between BenchKit common flow and package-owned behavior is much clearer now, but metadata discovery, generalization across multiple detailed packages, and package-level comparison are not yet fixed.
- application-side estimation declaration API:
  the direction of declaring current / future packages and section bindings in `estimate.sh` is becoming clear, but the final cross-application API is not yet frozen.
- estimation compare UI:
  detail views now expose current / future breakdown, fallback, and applicability, but same-`code`/`exp` comparison remains intentionally deferred.
- result quality summary handling:
  the SPEC requires portal-side result-quality summary presentation, but it does not define quality-score thresholds or PR gates. Quality badges, detail views, and latest-result current-state summaries are therefore treated as internal, visibility-first presentation features, not as standalone quantity or quality gaps.
- site capability checker:
  the `/results/usage` configuration check that public `system_info.csv` entries resolve to `system.csv` / `queue.csv` is now promoted to CI preflight, while the app support matrix remains portal visibility rather than a CI failure because application readiness intentionally varies.
- app/system capability visibility:
  the current coverage matrix uses `list.csv` plus structured shell-branch detection in `build.sh` / `run.sh`, but it is intentionally not a full execution-contract gate at this stage. The functional gap is limited to the missing capability summaries and validation paths needed for site onboarding and operations decisions required by the SPEC.
- result portal verification path:
  the portal now has a fixed repo-local Python dependency manifest, a standard test entrypoint, and a lightweight CI path for portal-oriented changes, but the path filter coverage must continue to track upload helpers, portal display metadata, and nearby operational entrypoints as the surface area expands.

### 2.1.1 GAP として扱う範囲 / What Counts as a Functional Gap

この文書では、次のようなものを本質的な機能 GAP として扱う。

1. SPEC が要求する user / operator workflow が未実装または未接続である。
2. 他機能の入力になる data contract、shell API、portal API が未固定で、横展開や自動化を阻害している。
3. app / site / estimation package の追加者が従うべき責務境界が不明確で、実装者ごとの判断に依存している。
4. portal、CI、runner、Git の間の導線が未接続で、仕様上の運用を end-to-end で完了できない。
5. provenance、usage accounting、approval など、後続の比較・監査・自動化に必要な意味付けが不足している。

一方、次は SPEC が明示的に要求していない限り、単独では GAP としない。

- test file 数、test case 数、coverage 率
- 対応済み app / system / site の数
- quality score や badge の閾値
- UI の見た目の完成度や説明量
- 内部 visibility 用の warning / candidate の数

result quality については、SPEC が求める「portal での品質サマリ表示」は機能として扱う。
ただし、`source_info`、`fom_breakdown`、artifact 参照などの充足率や quality score は、現時点では通常 PR の blocking rule にしない。
それらは内部管理・改善候補として visibility-first で扱う。

This document treats the following as functional gaps:

1. a user or operator workflow required by the SPEC is not implemented or not connected;
2. a data contract, shell API, or portal API needed by other functions is not fixed;
3. responsibility boundaries for adding applications, sites, or estimation packages remain unclear;
4. portal, CI, runner, and Git workflows cannot complete the required operation end to end;
5. provenance, usage accounting, approval, or similar semantics needed for later comparison, audit, or automation are missing.

The following are not standalone gaps unless the SPEC explicitly requires them: test counts, coverage rates, the number of supported apps/systems/sites, quality-score thresholds, UI polish, or the number of internal warnings.

### 2.1.2 文書で解決済みまたは GAP から外すもの / Items Resolved by Documentation or Out of Scope as Gaps

現時点で文書整理により GAP から外せるものは次の通りである。

- 役割名:
  現時点の repo 変更・PR 確認・手動 CI 運用では、app 担当、拠点担当、推定担当、admin を基本ロールとし、admin が reviewer / approver を兼ねる運用でよい。申請者は将来の portal 申請・承認 workflow のロールであり、現時点の文書整理で解決する責務分担には含めない。将来 workflow を実装する場合にのみ、申請者を含む権限 enforcement を機能 GAP として扱う。
- 責務分離:
  app 担当は `programs/<code>/` 配下の build/run/list/estimate と app 固有の採取を主に持つ。拠点担当は `config/system.csv`、`config/queue.csv`、`config/system_info.csv` と runner / scheduler / queue 条件を持つ。推定担当は `scripts/estimation/packages/` と `scripts/estimation/section_packages/` 配下の推定ロジック、metadata、fallback / applicability を持つ。BenchKit 共通層は common flow、JSON 受け渡し、portal 表示、CI / helper を持つ。この分担は `docs/guides/developer-reference.md`、`add-app.md`、`add-site.md`、`add-estimation.md`、`add-estimation-package.md` で案内する。
- scaffold:
  scaffold や自動生成は必須要件ではない。既存例と guide から追加できる状態を正とし、必要に応じて任意の支援機能として検討する。
- coverage matrix:
  app / system coverage matrix は現時点では visibility であり、PR blocking rule ではない。SPEC が明示的に gate を求めるまでは、未対応の組み合わせを可視化するための情報として扱う。
- result quality:
  quality badge、quality score、source / breakdown / artifact の充足率は通常 PR の blocking rule ではない。KPI として使う可能性はあるが、現時点では GAP ではなく参考値である。
- test counts / supported counts:
  test file 数、test case 数、対応 app / system / site 数は参考値であり、SPEC が閾値を定義しない限り GAP ではない。
- site onboarding:
  拠点登録の基本導線と責務分担は既存 guide でかなり説明済みである。追加で GAP として扱うのは、自動 validation や capability summary が運用判断に必要になった場合に限る。

推定 package の配置場所や細かな登録仕様は今後変更される可能性がある。
そのため、この文書では「現時点の責務分担」を明記するに留め、永続的なディレクトリ構造そのものを SPEC レベルの固定事項とは扱わない。

## 3. 機能別ギャップ分析 / Function-by-Function Gap Analysis

本質的な機能 GAP は、現時点では次の領域に集約される。

1. 推定 package の metadata discovery、複数 package の選択・fallback・比較導線が未固定である。
2. `qws` 以外の app へ推定を横展開するための `estimate.sh` 宣言 API と共通実行契約がまだ十分に固まっていない。
3. 再推定の portal 起動、履歴比較、差分表示が end-to-end の利用導線として未完成である。
4. Result JSON / Estimate JSON / provenance の契約は実装が進んでいるが、app 横断で何を必須・任意・非 git source として扱うかの運用契約が未固定である。
5. site onboarding と capability summary は docs と portal visibility が中心で、runner / scheduler / queue 条件を自動確認して運用判断に使う導線がまだ弱い。
6. 使用量集計は node-hour 中心で、予算主体・アカウント主体・runner 主体との結び付きが未実装である。
7. 申請・承認・自動 PR、AI 駆動最適化、read-only MCP は構想段階で、SPEC が示す将来 workflow をまだ実行できない。申請者など将来 workflow 固有のロールは、portal 上の申請・承認・権限 enforcement を実装する時点の課題として扱う。

The essential functional gaps currently concentrate in estimation-package discovery and comparison, cross-application estimation rollout, re-estimation workflows, provenance contracts, site capability validation, usage-accounting dimensions, and approval/AI/MCP workflows. Contributor responsibility boundaries are documented through existing guides and estimation-package specifications; scaffolding may help, but is not treated as a mandatory gap at this stage.

| 機能 | 仕様要求 | 現状実装 | 不足・課題 | 他機能への影響 | 優先度 |
|---|---|---|---|---|---|
| ベンチマーク実行定義 | アプリごとの build/run/list を保持し、継続実行可能であること | `programs/*` に `build.sh` `run.sh` `list.csv`、一部 `estimate.sh` がある。追加や修正は既存例を見ながら行う運用が中心である | 機能 GAP として残るのは、将来の申請・承認 workflow から app / run 条件変更へ接続する導線が未実装であること。責務境界や置き場所は既存 guide / spec で定義できる | 申請・承認・AI 連携の前提になる | 高 |
| CI ジョブ生成 | system と queue 情報を使って CI 実行を生成すること | `matrix_generate.sh` と `job_functions.sh` が実装済み。`add-site.md` に `system.csv` / `queue.csv` / `system_info.csv` の責務分担、接続確認順序、障害切り分け、onboarding checklist も整理された。portal の `/results/usage` では queue 定義抜けや `system_info.csv` 未登録を軽く確認できる。さらに公開 `system_info.csv` が `system.csv` と `queue.csv` に対応することは `result_server/tests/check_site_config.py` で CI preflight 化済み | site ごとの capability summary と、runner / scheduler / queue 条件を運用判断へつなぐ自動 validation が未実装。app support matrix は visibility 扱いであり、SPEC が gate を求めるまでは GAP としない | 拠点追加、予算管理、申請フォームの自動化に影響 | 高 |
| 結果正規化 | `run.sh` 出力を Result JSON に正規化すること | `bk_emit_result`、`bk_emit_section`、`bk_emit_overlap`、`result.sh` が実装済み。portal 側では一覧の quality badge と詳細の `Quality` セクションで `source_info`、`fom_breakdown`、推定入力参照の有無を軽く確認でき、`/results/usage` では最新 result ベースの current-state も見られる | app 横断で Result JSON の必須・任意 field、provenance、estimation input 参照をどう扱うかの契約と validation 導線が未固定 | 推定、可視化、AI 診断の入力契約に直結 | 高 |
| 性能推定 | Result JSON から Estimate JSON を生成し、可視化可能であること | `scripts/estimation/common.sh`、`scripts/estimation/run.sh`、`scripts/result_server/send_estimate.sh`、`estimated` 画面あり。`qws` では `weakscaling` と詳細ダミー推定、section ごとの package 指定、補助データ参照、section-level fallback、requested/applied package 識別、top-level applicability end state、推定元 result と推定結果自体の UUID / timestamp 保持まで動作する | 横展開はまだ `qws` 中心。複数 detailed package の本実装、再推定比較運用、他 app への適用が未完成 | AI 駆動、将来機評価、継続的フィードバックの基盤になる | 最優先 |
| 推定結果表示 | Estimate JSON を一覧・詳細で表示できること | `result_server/routes/estimated.py` とテンプレートが実装済み。requested/applied package、applicability、estimate UUID の基本表示に加えて、HTML detail で current / future breakdown、section / overlap 単位の fallback / package applicability まで表示できる。home からの導線も整理済みで、未認証時は login required であることも入口で分かる | compare UI、`not_applicable` の説明補助、複数 estimate 間の差分把握はまだ弱い | 推定運用を本格化すると重要度が上がる | 高 |
| 使用量集計 | 実行使用量を集計し、運用判断に使えること | `node_hours.py` と `/results/usage` が実装済み。node-hour 集計に加えて、登録済み system と app の対応状況を `list.csv` および `build.sh` / `run.sh` の検出に基づく coverage matrix で確認できる。さらに `system.csv` / `queue.csv` / `system_info.csv` の軽い診断、partial support、最新 result ベースの quality / source tracking current-state も表示できる | 予算主体、アカウント主体、runner 主体との結び付きや、site capability を使用量判断へつなぐ導線が未実装 | 多拠点運用と予算管理の核になる | 高 |
| ソース出自情報 | 最上位アプリケーションの commit hash を追跡すること | `bk_fetch_source` と `source_info` が実装済み。portal 側でも `/results/usage` に最新 result ベースの `source_status`、`source_type`、`source_reference`、不足 field が出せる | git source provenance の app 横断適用と、archive/file など非 git source の `source_reference` 契約・validation semantics が未固定 | 推定比較、AI 最適化、回帰分析の再現性に直結 | 高 |
| 拠点接続 | runner, scheduler, queue, site 条件を扱えること | `system.csv` と CI 生成が連携済み。`system_info.csv` を含めた責務分担、接続確認手順、障害切り分け、site onboarding checklist が docs に整理済みで、portal 側でも軽い configuration checks が見える | docs 依存がまだ強く、site ごとの capability summary、接続前提、queue/resource 条件を自動確認する導線が未実装 | 使用量集計、申請、runner 分散運用に直結 | 高 |
| 認証・権限 | 結果・管理機能へのアクセス制御を行うこと | TOTP、admin、閲覧制御あり。app 担当、拠点担当、推定担当、admin / reviewer / approver の作業上の責務は文書上整理できる | 現時点の GAP は role 名そのものではなく、申請者を含む申請・承認 workflow を portal 上で実行する場合の権限 enforcement が未実装であること | 申請・承認・AI 指示導入時に重要になる | 中 |
| shell-first 共通化 | shell を保ったまま共通処理を吸収すること | `bk_emit_*` と `bk_fetch_source` は導入済み。app / site / estimation package 追加者の責務境界は guide と estimation package 仕様に整理した | scaffold や部分生成は任意の支援機能であり必須ではない。現時点では機能 GAP として扱わない | app 追加の敷居を下げ、推定横展開も楽にする | 完了扱い |
| 申請・承認・自動PR | ポータルから変更要求を受け、承認後に Git へ落とせること | 構想のみ | 未実装 | app 追加、条件変更、推定モデル変更の運用負荷を大きく下げる | 高 |
| AI 駆動最適化連携 | AI が最適化提案や変更提案に参加できること | 構想のみ | 対象データ、承認フロー、評価指標、再実行ループが未定義 | 推定が先に固まるほど設計しやすくなる | 高 |
| MCP 連携 | 外部エージェントやツールが制御された形で情報取得・操作できること | 構想のみ | read-only から始める API / ツール設計が未着手 | AI 連携、ポータル連携、外部ツール連携の共通面になる | 中 |

## 4. 相互依存と順序効果 / Dependencies and Sequencing Effects

### 4.1 性能推定を先に固める効果 / Why Estimation Should Come First

性能推定は、単独の 1 機能ではなく、以下の複数機能の接続点になっている。

- Result JSON の契約
- source_info / provenance の契約
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

- Result JSON contracts
- source_info / provenance contracts
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

`build.sh` / `run.sh` の共通関数、既存例、責務境界が整うほど、複雑な YAML DSL を導入する必要は小さくなる。

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

### 5.2 併走で維持すべき領域: result portal 検証導線と Python 実行環境 / Parallel Area to Maintain: Result Portal Verification Path and Python Runtime

`result_server` の検証導線は、SPEC 上の本質的な機能 GAP というより、portal 機能を壊さず増やすための運用基盤である。
テスト数や coverage 率を GAP として追うのではなく、portal / upload helper / config 表示変更が適切な lightweight verification に接続されているかを維持対象とする。

- `result_server/tests` には pytest ベースのテストスイートがあり、portal 側はすでに「検証すべき対象」になっている
- repo-local な依存関係定義として `requirements-result-server.txt` があり、`result_server/tests/run_result_server_tests.py` が標準 test entrypoint として使える
- portal-oriented 変更向けの lightweight GitHub Actions として `.github/workflows/result-server-tests.yml` が用意されている
- `.gitlab-ci.yml` は直接または手動起動されたGitLab pipelineで `result_server/**/*` や `config/system_info.csv` 変更時に重い benchmark pipeline を skip する。保護ブランチ同期自体は `ci.skip` を使うため、GitHub Actions 側の path filter を portal 周辺の実ファイルに追従させ続ける必要がある

したがって短期的には、性能推定の横展開と並行して、次を維持・拡張する価値が高い。

1. `requirements-result-server.txt` を portal の依存追加に追従させる
2. `result_server/tests/run_result_server_tests.py` を標準 test entrypoint として保つ
3. `.github/workflows/result-server-tests.yml` の path filter を portal-oriented 変更に追従させる

これは性能推定の優先度を下げるためではなく、推定結果表示・認証・比較 UI の変更が増えるほど、portal 回帰の検出が重要になるためである。

#### 5.2.1 CI 関連維持タスク / CI Maintenance Tasks

CI 関連の残作業は、「仕組みを新規に置く」段階から「対象範囲を運用に耐える形へ広げ、古くならないようにする」段階へ移っている。
短期的な実装・確認は次の状態まで進んでいる。

1. `result-server-tests.yml` の path filter は、`result_server/**/*`、`scripts/bk_functions.sh`、`scripts/result.sh`、`scripts/result_server/**`、profile-data shell tests、`config/system.csv`、`config/queue.csv`、`config/system_info.csv`、`requirements-result-server.txt` を対象にする形へ更新済みである。
2. `.gitlab-ci.yml` の heavy benchmark skip rules と `docs/ci.md` の説明は、root Markdown、`docs/**/*`、`result_server/**/*`、`requirements-result-server.txt`、`config/system_info.csv` の skip 対象について同期済みである。一方、`scripts/bk_functions.sh`、`scripts/result.sh`、`scripts/result_server/**` は GitHub Actions の lightweight verification 対象でもあるが、直接または手動で GitLab pipeline を起動した場合は `.gitlab-ci.yml` の `scripts/**/*` rule により benchmark-affecting として実行される。
3. 手動 GitLab CI は、`qws` / `MiyabiG` の最小実行で GitLab pipeline 起動から推定まで確認済みである。Pipeline API variables は JSON payload で渡す。
4. protected branch sync は、`ci.skip` により GitLab mirror 更新時に GitLab CI が自動起動しないことを運用上確認済みである。

docs-only / portal-only / benchmark-code / CI-config の代表的な変更セットは、`docs/ci.md` の examples として整理済みである。
公開 `system_info.csv` に載せた system が `system.csv` と `queue.csv` に到達できることは、`result_server/tests/check_site_config.py` による CI preflight として整理済みである。逆に、開発用・非公開用の `system.csv` / `queue.csv` 定義が `system_info.csv` に載っていないことは許容する。
app support matrix、partial support、app entrypoint 欠落、`list.csv` の未知 system などは、アプリごとの準備状況や導入段階に依存するため、現時点では CI failure ではなく `/results/usage` の visibility として扱う。

完了条件は、変更種別ごとの期待 CI 経路が文書化され、path filter と skip rules がその期待に一致し、portal 実装変更が heavy benchmark を起動せず lightweight verification で捕捉されることである。Result JSON / upload helper の変更は lightweight verification でまず捕捉しつつ、GitLab pipeline を明示起動した場合は benchmark-affecting script として扱う。Result JSON quality は portal 内の内部管理として可視化し、SPEC が明示的な gate を要求しない限り、通常 PR の blocking rule にはしない。

### 5.3 次点: AI 駆動最適化連携 / Next Priority: AI-Driven Optimization

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
4. `result_server` 用の lightweight CI、標準 test entrypoint、依存 manifest を portal 周辺の変更に追従させる
5. ローカル再現手順と CI path filter の対象範囲を定期的に見直す
6. Estimate JSON と portal 表示を section / overlap 詳細まで整える
7. 再推定比較の UI / API を整える
8. package metadata discovery を portal や比較導線に活かす

### 6.2 中期 / Mid Term

1. 拠点接続の onboarding / validation を仕様化する
2. 使用量集計に予算主体・runner 主体の概念を入れる
3. app 追加と条件変更の申請・承認フローを設計する
4. app / site / estimation package 追加時の責務境界と配置ルールを、実装の変化に合わせて更新する

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
