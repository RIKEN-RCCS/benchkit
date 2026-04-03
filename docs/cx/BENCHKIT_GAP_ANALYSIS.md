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

However, continuous estimation currently has only an entry-point implementation, and AI-driven optimization integration remains mostly at the integration-point stage.

## 3. 機能別ギャップ分析 / Function-by-Function Gap Analysis

| 機能 | 仕様要求 | 現状実装 | 不足・課題 | 他機能への影響 | 優先度 |
|---|---|---|---|---|---|
| ベンチマーク実行定義 | アプリごとの build/run/list を保持し、継続実行可能であること | `programs/*` に `build.sh` `run.sh` `list.csv`、一部 `estimate.sh` がある | 追加や修正がまだ人手中心。雛形生成や申請導線がない | 申請・承認・AI 連携の前提になる | 高 |
| CI ジョブ生成 | system と queue 情報を使って CI 実行を生成すること | `matrix_generate.sh` と `job_functions.sh` が実装済み | 拠点接続の検証や onboarding 手順が未整理 | 拠点追加、予算管理、申請フォームの自動化に影響 | 高 |
| 結果正規化 | `run.sh` 出力を Result JSON に正規化すること | `bk_emit_result`、`bk_emit_section`、`bk_emit_overlap`、`result.sh` が実装済み | app ごとの差異を自動検証する仕組みが弱い | 推定、可視化、AI 診断の入力品質に直結 | 高 |
| 性能推定 | Result JSON から Estimate JSON を生成し、可視化可能であること | `estimate_common.sh`、`run_estimate.sh`、`send_estimate.sh`、`estimated` 画面あり | 実際の `estimate.sh` は `qws` のみ。モデル表現、再推定運用、比較基準の仕様がまだ薄い | AI 駆動、将来機評価、継続的フィードバックの基盤になる | 最優先 |
| 推定結果表示 | Estimate JSON を一覧・詳細で表示できること | `result_server/routes/estimated.py` とテンプレートが実装済み | モデル情報、前提条件、信頼性の見せ方がまだ弱い | 推定運用を本格化すると重要度が上がる | 高 |
| 使用量集計 | 実行使用量を集計し、運用判断に使えること | `node_hours.py` と `/results/usage` が実装済み | 予算主体、アカウント主体、runner 主体との結び付きがない | 多拠点運用と予算管理の核になる | 高 |
| ソース出自情報 | 最上位アプリケーションの commit hash を追跡すること | `bk_fetch_source` と `source_info` が実装済み | すべての app で徹底されていない。 archive/file の場合は commit hash を持てない | 推定比較、AI 最適化、回帰分析の再現性に直結 | 高 |
| 拠点接続 | runner, scheduler, queue, site 条件を扱えること | `system.csv` と CI 生成が連携済み | 拠点接続の明示仕様、接続確認手順、障害切り分けが未整備 | 使用量集計、申請、runner 分散運用に直結 | 高 |
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
- 再推定のトリガ、履歴、比較表示

現状は `qws` のみが `estimate.sh` を持つため、実装としては入口確認段階である。
ここを複数 app に横展開できる形へ引き上げる必要がある。

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

1. 性能推定仕様を詳細化する
2. Estimate JSON と portal 表示を整える
3. `estimate.sh` のテンプレートまたは共通補助を整える
4. `qws` 以外に 1 から 2 本の app へ推定を横展開する
5. source_info の実装徹底状況を点検する

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
3. `SITE_INTEGRATION_SPEC.md`
4. `REQUEST_APPROVAL_SPEC.md`
5. `AI_OPTIMIZATION_POC.md`

If performance estimation is the top priority, the next documents to write should be:

1. `ESTIMATION_SPEC.md`
2. `ESTIMATE_JSON_SPEC.md`
3. `SITE_INTEGRATION_SPEC.md`
4. `REQUEST_APPROVAL_SPEC.md`
5. `AI_OPTIMIZATION_POC.md`
