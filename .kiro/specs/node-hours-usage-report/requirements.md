# 要件定義書

## はじめに

result_server Flaskアプリケーションに、アプリケーション（code）×システム（system）の組み合わせごとのノード時間使用量を集計・表示するページを追加する。集計期間は月次、半期（上期：4月〜9月、下期：10月〜3月）、年度（4月〜3月）の3種類を切り替えて表示できる。日本の会計年度（4月始まり）に準拠する。

ノード時間の計算式:
- cross モード: `node_count × run_time_seconds / 3600`
- native モード: `node_count × (build_time_seconds + run_time_seconds) / 3600`

native モードではビルドと実行が同一計算ノード上で行われるため、ビルド時間もノード占有時間に含める。

データソースは `received/` ディレクトリ内の結果JSONファイルであり、各ファイルのファイル名に含まれるタイムスタンプ（`YYYYMMDD_HHMMSS`）を集計期間の判定に使用する。

## 用語集

- **Result_Server**: 結果データを管理・表示するFlask Webアプリケーション
- **Usage_Report_Page**: ノード時間使用量の集計結果を表示するページ
- **Node_Hours_Aggregator**: 結果JSONファイルからノード時間を集計するモジュール
- **Result_JSON**: `received/` ディレクトリに格納される個別の実行結果JSONファイル
- **App**: Result_JSON内の `code` フィールドで識別されるアプリケーション名
- **System**: Result_JSON内の `system` フィールドで識別されるシステム名
- **Node_Hours**: ノード占有時間。cross モード: `node_count × run_time / 3600`、native モード: `node_count × (build_time + run_time) / 3600`
- **Fiscal_Year**: 日本の会計年度。4月1日から翌年3月31日まで（例: FY2025 = 2025年4月〜2026年3月）
- **First_Half**: 会計年度の上期。4月1日から9月30日まで
- **Second_Half**: 会計年度の下期。10月1日から3月31日まで
- **Period_Type**: 集計期間の種類（月次 / 半期 / 年度）
- **Confidential_Filter**: 機密タグに基づくアクセス制御フィルタ

## 要件

### 要件 1: ノード時間使用量レポートページへのアクセス

**ユーザーストーリー:** 管理者として、ナビゲーションからノード時間使用量レポートページにアクセスしたい。各アプリケーションがどのシステムでどれだけ計算資源を使っているか把握するためである。

#### 受入基準

1. THE Usage_Report_Page SHALL `/results/usage` のURLパスで利用可能とする
2. WHILE ユーザーがadmin権限で認証済みの状態で、THE Result_Server SHALL ナビゲーションバーにノード時間使用量レポートページへのリンクを表示する
3. WHEN 未認証ユーザーがUsage_Report_Pageにアクセスした場合、THE Result_Server SHALL ログインページにリダイレクトする
4. WHEN 認証済みだがadmin権限を持たないユーザーがUsage_Report_Pageにアクセスした場合、THE Result_Server SHALL 403 Forbiddenを返す

### 要件 2: ノード時間の計算

**ユーザーストーリー:** 管理者として、各実行結果のノード時間を正確に算出したい。計算資源の使用量を定量的に把握するためである。

#### 受入基準

1. WHEN Result_JSONの `execution_mode` が `cross` の場合、THE Node_Hours_Aggregator SHALL `node_count` × `pipeline_timing.run_time`（秒）/ 3600 の計算式でノード時間を算出する
2. WHEN Result_JSONの `execution_mode` が `native` の場合、THE Node_Hours_Aggregator SHALL `node_count` × (`pipeline_timing.build_time` + `pipeline_timing.run_time`)（秒）/ 3600 の計算式でノード時間を算出する
3. IF Result_JSONに `node_count` フィールドが存在しないか数値でない場合、THEN THE Node_Hours_Aggregator SHALL 該当レコードをノード時間0として扱う
4. IF Result_JSONに `pipeline_timing.run_time` フィールドが存在しないか数値でない場合、THEN THE Node_Hours_Aggregator SHALL 該当レコードをノード時間0として扱う
5. IF native モードで `pipeline_timing.build_time` フィールドが存在しないか数値でない場合、THEN THE Node_Hours_Aggregator SHALL build_time を0として扱い、run_time のみで算出する
6. THE Node_Hours_Aggregator SHALL ノード時間を小数点以下2桁に丸めて表示する

### 要件 3: 期間タイプの切り替え

**ユーザーストーリー:** 管理者として、月次・半期・年度の3種類の集計期間を切り替えて表示したい。異なる粒度で使用量の傾向を確認するためである。

#### 受入基準

1. THE Usage_Report_Page SHALL 月次、半期、年度の3つのPeriod_Typeを切り替えるUIコントロールを表示する
2. WHEN ユーザーがPeriod_Typeを「月次」に選択した場合、THE Usage_Report_Page SHALL 各月（例: 2025年4月、2025年5月…）ごとの集計結果を表示する
3. WHEN ユーザーがPeriod_Typeを「半期」に選択した場合、THE Usage_Report_Page SHALL 上期（4月〜9月）と下期（10月〜3月）ごとの集計結果を表示する
4. WHEN ユーザーがPeriod_Typeを「年度」に選択した場合、THE Usage_Report_Page SHALL 会計年度（4月〜翌3月）ごとの集計結果を表示する
5. THE Usage_Report_Page SHALL デフォルトのPeriod_Typeとして「年度」を選択した状態で表示する

### 要件 4: 会計年度の選択

**ユーザーストーリー:** 管理者として、表示する会計年度を選択したい。特定の年度の使用量を確認するためである。

#### 受入基準

1. THE Usage_Report_Page SHALL 利用可能な会計年度のドロップダウンリストを表示する
2. THE Node_Hours_Aggregator SHALL Result_JSONファイル名のタイムスタンプ（`YYYYMMDD_HHMMSS`パターン）から日付を抽出し、会計年度を判定する
3. WHEN タイムスタンプの月が1月〜3月の場合、THE Node_Hours_Aggregator SHALL 該当レコードを前年の会計年度に分類する（例: 2026年1月 → FY2025）
4. WHEN タイムスタンプの月が4月〜12月の場合、THE Node_Hours_Aggregator SHALL 該当レコードをその年の会計年度に分類する（例: 2025年9月 → FY2025）
5. THE Usage_Report_Page SHALL デフォルトで現在の会計年度を選択した状態で表示する

### 要件 5: クロス集計テーブルの表示

**ユーザーストーリー:** 管理者として、アプリケーション×システムのクロス集計テーブルでノード時間を確認したい。どのアプリがどのシステムでどれだけ使っているか一目で把握するためである。

#### 受入基準

1. THE Usage_Report_Page SHALL 行にApp名、列にSystem名を配置したクロス集計テーブルを表示する
2. THE Usage_Report_Page SHALL 各セルに該当するApp×Systemの組み合わせのノード時間合計値を表示する
3. THE Usage_Report_Page SHALL 各行の末尾にApp別の合計値を表示する
4. THE Usage_Report_Page SHALL 各列の末尾にSystem別の合計値を表示する
5. THE Usage_Report_Page SHALL テーブルの右下隅に全体の総合計値を表示する
6. WHEN 該当するApp×Systemの組み合わせにデータが存在しない場合、THE Usage_Report_Page SHALL セルに「-」を表示する
7. THE Usage_Report_Page SHALL App名をアルファベット順にソートして行を表示する
8. THE Usage_Report_Page SHALL System名をアルファベット順にソートして列を表示する

### 要件 6: 機密データの取り扱い

**ユーザーストーリー:** 管理者として、ノード時間レポートでは機密データを含む全てのResult_JSONを集計対象としたい。admin限定ページであるため全データを把握する必要があるためである。

#### 受入基準

1. THE Node_Hours_Aggregator SHALL Usage_Report_Pageがadmin限定であるため、confidentialタグの有無に関わらず全てのResult_JSONを集計対象に含める

### 要件 7: 月次表示での期間列

**ユーザーストーリー:** 管理者として、月次表示では選択した会計年度の各月が列として表示されることを期待する。月ごとの使用量推移を確認するためである。

#### 受入基準

1. WHEN Period_Typeが「月次」の場合、THE Usage_Report_Page SHALL 選択された会計年度の12ヶ月分（4月〜翌3月）の列を持つテーブルを表示する
2. WHEN Period_Typeが「月次」の場合、THE Usage_Report_Page SHALL 各月の列ヘッダーに「YYYY年M月」形式で表示する
3. THE Usage_Report_Page SHALL 各セルに該当月のApp×Systemのノード時間合計値を表示する

### 要件 8: 半期表示での期間列

**ユーザーストーリー:** 管理者として、半期表示では上期・下期の集計結果を確認したい。半年単位での使用量を把握するためである。

#### 受入基準

1. WHEN Period_Typeが「半期」の場合、THE Usage_Report_Page SHALL 選択された会計年度の上期（First_Half）と下期（Second_Half）の2列を持つテーブルを表示する
2. THE Usage_Report_Page SHALL 上期の列ヘッダーに「上期（4月〜9月）」、下期の列ヘッダーに「下期（10月〜3月）」と表示する

### 要件 9: 年度表示での集計

**ユーザーストーリー:** 管理者として、年度表示では選択した会計年度の年間合計を確認したい。年間の計算資源使用量を把握するためである。

#### 受入基準

1. WHEN Period_Typeが「年度」の場合、THE Usage_Report_Page SHALL 選択された会計年度の年間合計を1列で表示する
2. THE Usage_Report_Page SHALL 年度列のヘッダーに「FY{年度}」形式（例: FY2025）で表示する

### 要件 10: データが存在しない場合の表示

**ユーザーストーリー:** 管理者として、選択した期間にデータが存在しない場合に適切なメッセージを確認したい。データの有無を明確に把握するためである。

#### 受入基準

1. WHEN 選択された会計年度とPeriod_Typeの組み合わせに該当するResult_JSONが存在しない場合、THE Usage_Report_Page SHALL 「該当期間のデータがありません」というメッセージを表示する
2. THE Usage_Report_Page SHALL データが存在しない場合でも期間選択UIは操作可能な状態を維持する
