# Requirements Document

## Introduction

BenchKit結果サーバ（Flask）にベクトル型メトリクスのグラフ表示機能およびリグレッションテスト機能を追加する。現在、結果一覧テーブルにはスカラー値（FOM）のみ表示されているが、BenchParkから取り込んだ結果にはベクトル型メトリクス（例: OSU Micro-Benchmarksのメッセージサイズ vs バンド幅/レイテンシ）が含まれる。本機能により、これらのベクトル型メトリクスをCDN経由のJavaScriptグラフライブラリを用いたインタラクティブなグラフとして可視化し、スカラー型メトリクスやビルド情報も詳細ページで表示する。さらに、同一システム・アプリケーションの結果を時系列で比較し、パフォーマンスリグレッションを検出する機能を提供する。

## Glossary

- **Result_Server**: BenchKit結果サーバ。Flask + Jinja2テンプレートで構成されたWebアプリケーション
- **Results_Table**: 結果一覧テーブル。`_results_table.html`テンプレートで描画される結果の一覧表
- **Detail_Page**: 個別結果の詳細表示ページ。グラフ、データテーブル、ビルド情報を表示する新規ページ
- **Vector_Metrics**: ベクトル型メトリクス。結果JSONの`metrics.vector`に格納される、X軸（message_size等）に対する複数系列のデータ
- **Scalar_Metrics**: スカラー型メトリクス。結果JSONの`metrics.scalar`に格納される、単一値のメトリクス群
- **Graph_Library**: CDN経由で読み込むJavaScriptグラフ描画ライブラリ。具体的なライブラリの選定は設計フェーズで決定する
- **Build_Info**: Spackビルド情報。結果JSONの`build`セクションに格納されるコンパイラ、MPI、パッケージ情報
- **Result_JSON**: BenchKit形式の結果JSONファイル。`received/`ディレクトリに保存される
- **Results_Loader**: 結果読み込みユーティリティ。`utils/results_loader.py`で実装される結果データの読み込み・フィルタリング機能
- **Comparison_Page**: リグレッション比較ページ。同一system+codeの複数結果を時系列で重ね合わせ表示する新規ページ
- **Result_Group**: 同一の`system`と`code`の組み合わせを持つ結果の集合

## Requirements

### Requirement 1: 結果一覧テーブルへの詳細リンク追加

**User Story:** As a ベンチマーク管理者, I want 結果一覧テーブルでベクトル型メトリクスを持つ結果を識別できるようにしたい, so that 詳細なパフォーマンスデータを素早く確認できる

#### Acceptance Criteria

1. WHEN Result_JSON に `metrics.vector` フィールドが存在する場合, THE Results_Table SHALL 該当行に詳細ページへのリンクを表示する
2. WHEN Result_JSON に `metrics.vector` フィールドが存在しない場合, THE Results_Table SHALL 該当行にリンクを表示せず、既存の表示を維持する
3. THE Results_Table SHALL 新規カラム「Detail」を既存カラムの後に追加し、詳細リンクの有無を表示する
4. WHEN ユーザーが詳細リンクをクリックした場合, THE Result_Server SHALL Detail_Page へ遷移する

### Requirement 2: 個別結果詳細ページの作成

**User Story:** As a ベンチマーク管理者, I want 個別結果の詳細情報をまとめて確認できるページがほしい, so that ベンチマーク結果を包括的に分析できる

#### Acceptance Criteria

1. THE Detail_Page SHALL 結果のメタ情報（code, system, Exp, FOM, FOM_unit, node_count, cpus_per_node）を表示する
2. WHEN Result_JSON に `metrics.vector` フィールドが存在する場合, THE Detail_Page SHALL ベクトル型メトリクスをグラフで可視化する
3. WHEN Result_JSON に `metrics.scalar` フィールドが存在する場合, THE Detail_Page SHALL スカラー型メトリクスを数値で確認できる形式で表示する
4. WHEN Result_JSON に `build` フィールドが存在する場合, THE Detail_Page SHALL Build_Info を表示する
5. THE Detail_Page SHALL 結果一覧ページへの戻りリンクを含む
6. IF 指定されたファイル名に対応する Result_JSON が存在しない場合, THEN THE Result_Server SHALL HTTP 404 エラーを返す

### Requirement 3: ベクトル型メトリクスのグラフ描画

**User Story:** As a ベンチマーク管理者, I want メッセージサイズに対するバンド幅やレイテンシの変化をグラフで確認したい, so that パフォーマンス特性を視覚的に把握できる

#### Acceptance Criteria

1. THE Detail_Page SHALL CDN経由のJavaScript Graph_Library を使用してベクトル型メトリクスのグラフを描画する
2. THE Detail_Page SHALL Vector_Metrics の `x_axis.name` をX軸ラベル、`x_axis.unit` をX軸単位として表示する
3. THE Detail_Page SHALL Vector_Metrics の `table.columns`（先頭のX軸カラムを除く）を個別の系列として描画する
4. THE Detail_Page SHALL X軸を対数スケールで表示する（メッセージサイズは1バイトから4MBまで指数的に増加するため）
5. THE Detail_Page SHALL 各系列を視覚的に区別可能な形式で描画する

### Requirement 4: ベクトル型メトリクスのデータテーブル表示

**User Story:** As a ベンチマーク管理者, I want グラフに加えて数値データもテーブルで確認したい, so that 正確な値を参照できる

#### Acceptance Criteria

1. THE Detail_Page SHALL Vector_Metrics の `table.columns` をヘッダー、`table.rows` を行としたHTMLテーブルを表示する
2. THE Detail_Page SHALL データテーブルをグラフの下に配置する
3. THE Detail_Page SHALL X軸カラムの値を整数として、メトリクスカラムの値を小数点以下2桁で表示する

### Requirement 5: スカラー型メトリクスの表示

**User Story:** As a ベンチマーク管理者, I want gpcnet等のスカラー型メトリクスも詳細ページで確認したい, so that 全種類のベンチマーク結果を統一的に閲覧できる

#### Acceptance Criteria

1. WHEN Result_JSON に `metrics.scalar` フィールドが存在し、キーが2つ以上ある場合, THE Detail_Page SHALL 各スカラーメトリクスをキー名と値のペアとして表示する
2. WHEN Result_JSON に `metrics.scalar` フィールドが存在するが、キーが「FOM」のみの場合, THE Detail_Page SHALL スカラーメトリクスセクションを表示しない（FOMはメタ情報セクションで既に表示されるため）

### Requirement 6: ビルド情報の表示

**User Story:** As a ベンチマーク管理者, I want ベンチマーク結果のビルド環境情報を確認したい, so that 結果の再現性を検証できる

#### Acceptance Criteria

1. WHEN Result_JSON に `build` フィールドが存在する場合, THE Detail_Page SHALL ビルドツール名（build.tool）を表示する
2. WHEN Result_JSON に `build.spack` フィールドが存在する場合, THE Detail_Page SHALL コンパイラ名・バージョン（build.spack.compiler）を表示する
3. WHEN Result_JSON に `build.spack` フィールドが存在する場合, THE Detail_Page SHALL MPI名・バージョン（build.spack.mpi）を表示する
4. WHEN Result_JSON に `build.spack.packages` フィールドが存在する場合, THE Detail_Page SHALL パッケージ一覧（名前とバージョン）を表示する

### Requirement 7: リグレッション比較機能 - 結果選択

**User Story:** As a ベンチマーク管理者, I want 同じシステム・アプリケーションの過去の結果を選択して比較したい, so that パフォーマンスの経時変化を追跡できる

#### Acceptance Criteria

1. THE Results_Table SHALL 各行にチェックボックスを表示し、比較対象の結果を複数選択可能にする
2. WHEN ユーザーが2件以上の結果を選択した場合, THE Results_Table SHALL 比較ボタンを有効化する
3. WHEN ユーザーが比較ボタンをクリックした場合, THE Result_Server SHALL 選択された結果のファイル名をパラメータとして Comparison_Page へ遷移する
4. IF 選択された結果の `system` と `code` が一致しない場合, THEN THE Result_Server SHALL 比較できない旨のエラーメッセージを表示する

### Requirement 8: リグレッション比較機能 - ベクトル型メトリクスの重ね合わせ表示

**User Story:** As a ベンチマーク管理者, I want 異なる時点のベクトル型メトリクスを重ね合わせグラフで比較したい, so that メッセージサイズごとのパフォーマンス変化を視覚的に検出できる

#### Acceptance Criteria

1. WHEN 選択された結果が Vector_Metrics を持つ場合, THE Comparison_Page SHALL 同一メトリクス系列を結果ごとに異なる色で重ね合わせたグラフを描画する
2. THE Comparison_Page SHALL 各結果をタイムスタンプで識別可能なラベルで表示する
3. THE Comparison_Page SHALL X軸を対数スケールで表示する
4. THE Comparison_Page SHALL CDN経由のJavaScript Graph_Library を使用してグラフを描画する

### Requirement 9: リグレッション比較機能 - スカラー型メトリクスの時系列表示

**User Story:** As a ベンチマーク管理者, I want スカラー型メトリクスのFOM値を時系列で確認したい, so that パフォーマンスの推移傾向を把握できる

#### Acceptance Criteria

1. WHEN 選択された結果が Scalar_Metrics を持つ場合, THE Comparison_Page SHALL FOM値をタイムスタンプ順にグラフで表示する
2. THE Comparison_Page SHALL X軸にタイムスタンプ、Y軸にFOM値を配置する
3. THE Comparison_Page SHALL CDN経由のJavaScript Graph_Library を使用してグラフを描画する

### Requirement 10: 既存機能との互換性

**User Story:** As a ベンチマーク管理者, I want 既存の結果表示機能が影響を受けないことを保証したい, so that 運用中のシステムが安定して動作し続ける

#### Acceptance Criteria

1. THE Result_Server SHALL `metrics` フィールドを持たない既存形式の Result_JSON を従来通り結果一覧テーブルに表示する
2. THE Result_Server SHALL 既存のOTP認証・confidentialフィルタリング機能を Detail_Page および Comparison_Page にも適用する
3. THE Result_Server SHALL devモード（app_dev_flask.py）と本番モード（app.py）の両方で Detail_Page および Comparison_Page を利用可能にする
4. THE Results_Table SHALL 既存のカラム（Timestamp, SYSTEM, CODE, FOM, FOM version, Exp, Nodes, JSON, PA Data）の表示を変更しない

### Requirement 11: ルーティングとAPI

**User Story:** As a 開発者, I want 詳細ページと比較ページのURLが一貫したパターンに従うようにしたい, so that ブックマークや共有が容易になる

#### Acceptance Criteria

1. THE Result_Server SHALL `/results/detail/<filename>` のURLパターンで Detail_Page を提供する
2. THE Result_Server SHALL `/results/compare` のURLパターンで Comparison_Page を提供する（選択されたファイル名はクエリパラメータで受け取る）
3. THE Result_Server SHALL 既存の `/results/<filename>` エンドポイント（JSON表示）を変更しない
4. WHEN confidentialタグ付きの Result_JSON に対して未認証ユーザーがアクセスした場合, THE Result_Server SHALL HTTP 403 エラーを返す
