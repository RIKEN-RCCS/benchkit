# 実装計画: ノード時間使用量レポート

## 概要

`utils/node_hours.py` に集計ロジックを実装し、既存の `results_bp` Blueprint に `/usage` ルートを追加、`usage_report.html` テンプレートとナビゲーション更新を行う。既存のアーキテクチャパターン（Blueprint、`admin_required`、`_results_base.html` 継承、Hypothesis テスト）に準拠する。

## タスク

- [x] 1. ノード時間集計モジュールの作成
  - [x] 1.1 `result_server/utils/node_hours.py` を作成し、コアユーティリティ関数を実装する
    - `compute_node_hours(data)`: execution_mode に応じたノード時間計算（cross/native）
    - `extract_timestamp_from_filename(filename)`: ファイル名から `YYYYMMDD_HHMMSS` タイムスタンプ抽出
    - `get_fiscal_year(dt)`: 日付から会計年度を返す（1〜3月→前年、4〜12月→当年）
    - `get_fiscal_month_index(dt)`: 会計年度内の月インデックス（4月=0〜3月=11）
    - `get_half(dt)`: 上期（first）/下期（second）判定
    - 欠損・非数値フィールドのフォールバック処理を含む
    - _要件: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.2, 4.3, 4.4_

  - [ ]* 1.2 `compute_node_hours` のプロパティベーステストを作成する
    - **Property 1: ノード時間計算の正当性**
    - cross モード: `round(node_count × run_time / 3600, 2)`、native モード: `round(node_count × (build_time + run_time) / 3600, 2)`、欠損時: `0.0`
    - **検証対象: 要件 2.1, 2.2, 2.3, 2.4, 2.5**

  - [ ]* 1.3 小数点以下2桁の丸めプロパティテストを作成する
    - **Property 2: 小数点以下2桁の丸め**
    - `compute_node_hours` の戻り値が常に `value == round(value, 2)` を満たすことを検証
    - **検証対象: 要件 2.6**

  - [ ]* 1.4 会計年度分類のプロパティベーステストを作成する
    - **Property 3: 会計年度分類の正当性**
    - 1〜3月 → `year - 1`、4〜12月 → `year` を検証
    - **検証対象: 要件 4.3, 4.4**

- [x] 2. 集計関数の実装
  - [x] 2.1 `result_server/utils/node_hours.py` に `aggregate_node_hours` 関数を実装する
    - 指定ディレクトリの全JSONファイルを読み込み、ノード時間をクロス集計
    - 期間ラベル生成（monthly/semi_annual/fiscal_year）
    - apps/systems のアルファベット順ソート
    - row_totals, col_totals, grand_totals の算出
    - available_fiscal_years の抽出
    - confidential フィルタなし（admin専用のため全データ対象）
    - _要件: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 6.1, 7.1, 7.2, 7.3, 8.1, 8.2, 9.1, 9.2_

  - [ ]* 2.2 セル集計値のプロパティベーステストを作成する
    - **Property 4: セル集計値の正当性**
    - 各セル `table[app][system][period]` が該当レコードの `compute_node_hours` 合計と一致することを検証
    - **検証対象: 要件 5.2, 7.3**

  - [ ]* 2.3 合計値の整合性プロパティテストを作成する
    - **Property 5: 合計値の整合性**
    - 行合計 = 全Systemセル値合計、列合計 = 全Appセル値合計、総合計 = 全行合計の合計 = 全列合計の合計
    - **検証対象: 要件 5.3, 5.4, 5.5**

  - [ ]* 2.4 アルファベット順ソートのプロパティテストを作成する
    - **Property 6: アルファベット順ソート**
    - `apps` リストと `systems` リストがアルファベット昇順であることを検証
    - **検証対象: 要件 5.7, 5.8**

  - [ ]* 2.5 期間タイプ別の期間数プロパティテストを作成する
    - **Property 7: 期間タイプ別の期間数**
    - monthly → 12個、semi_annual → 2個、fiscal_year → 1個
    - **検証対象: 要件 7.1, 8.1, 9.1**

  - [ ]* 2.6 機密データ包含のプロパティテストを作成する
    - **Property 8: 機密データの包含**
    - confidential タグ付きResult JSONのノード時間が集計結果に含まれることを検証
    - **検証対象: 要件 6.1**

  - [ ]* 2.7 月次ラベルフォーマットのプロパティテストを作成する
    - **Property 9: 月次ラベルフォーマット**
    - monthly 期間ラベルが全て `YYYY年M月` 形式で、4月〜翌3月の順序であることを検証
    - **検証対象: 要件 7.2**

- [x] 3. チェックポイント - コアロジックの検証
  - 全テストが通ることを確認し、不明点があればユーザーに質問する。

- [x] 4. ルートとテンプレートの実装
  - [x] 4.1 `result_server/routes/results.py` に `/usage` ルートを追加する
    - `admin_required` デコレータを `routes/admin.py` から import して適用
    - クエリパラメータ `period_type`（デフォルト: `fiscal_year`）と `fiscal_year`（デフォルト: 現在の会計年度）を取得
    - 不正パラメータのフォールバック処理
    - `aggregate_node_hours` を呼び出して集計結果を取得
    - `usage_report.html` テンプレートをレンダリング
    - _要件: 1.1, 1.3, 1.4, 3.1, 3.5, 4.1, 4.5, 10.1, 10.2_

  - [x] 4.2 `result_server/templates/usage_report.html` テンプレートを作成する
    - `_results_base.html` を継承
    - 期間タイプ切り替えUI（月次/半期/年度ボタン）
    - 会計年度ドロップダウン
    - クロス集計テーブル（行=App、列=System×期間、行合計、列合計、総合計）
    - データなし時の「該当期間のデータがありません」メッセージ
    - セルにデータなしの場合は「-」を表示
    - _要件: 3.1, 3.2, 3.3, 3.4, 4.1, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.1, 7.2, 7.3, 8.1, 8.2, 9.1, 9.2, 10.1, 10.2_

  - [x] 4.3 `result_server/templates/_navigation.html` にadmin専用Usageリンクを追加する
    - `{% if 'admin' in session.get('user_affiliations', []) %}` 条件で表示
    - 認証済みユーザー向けナビゲーションリンク行に `📈 Usage` リンクを追加
    - _要件: 1.2_

  - [ ]* 4.4 ルートのユニットテストを作成する（`result_server/tests/test_usage_route.py`）
    - 未認証アクセス → ログインページリダイレクト
    - 非admin認証済みアクセス → 403 Forbidden
    - admin認証済みアクセス → 200 OK
    - デフォルトパラメータ（period_type=fiscal_year、現在の会計年度）
    - データなし時のメッセージ表示
    - ナビゲーションリンクの表示条件
    - _要件: 1.1, 1.2, 1.3, 1.4, 3.5, 4.5, 10.1_

- [ ] 5. ユニットテストの作成
  - [ ]* 5.1 `result_server/tests/test_node_hours.py` にコアロジックのユニットテストを作成する
    - `compute_node_hours`: cross/native モードの正常系、欠損フィールド、非数値フィールド
    - `get_fiscal_year`: 境界値（3月→前年度、4月→当年度）
    - `extract_timestamp_from_filename`: 正常パターン、タイムスタンプなしパターン
    - `get_half`: 上期/下期の境界値
    - 半期ラベル・年度ラベルのフォーマット確認
    - _要件: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.2, 4.3, 4.4_

- [x] 6. 最終チェックポイント - 全テスト通過確認
  - 全テストが通ることを確認し、不明点があればユーザーに質問する。

## 備考

- `*` マーク付きタスクはオプションであり、MVP優先の場合はスキップ可能
- 各タスクは具体的な要件番号を参照しトレーサビリティを確保
- チェックポイントでインクリメンタルな検証を実施
- プロパティテストは Hypothesis ライブラリを使用（既存プロジェクトで使用済み）
- プロパティテストファイル: `result_server/tests/test_node_hours_properties.py`
- ユニットテストファイル: `result_server/tests/test_node_hours.py`, `result_server/tests/test_usage_route.py`
