# 要件ドキュメント: result_server コードクリーンアップ

## はじめに

result_server コードベースの保守性向上を目的としたリファクタリング。ルート間・ユーティリティ間・テンプレート間に散在する重複コードの統合、未使用コードの除去、マジックナンバーの定数化、および共通パターンの一般化を行う。既存の機能・動作を一切変更せず、内部構造のみを改善する。

## 用語集

- **Result_Server**: ベンチマーク結果の受信・表示・管理を行う Flask ベースの Web アプリケーション
- **Route_Module**: Flask Blueprint として実装された各ルーティングモジュール（results.py, estimated.py, admin.py 等）
- **Results_Loader**: 結果 JSON ファイルの読み込み・フィルタリング・ページネーションを担当するユーティリティモジュール（utils/results_loader.py）
- **File_Permission_Checker**: confidential タグに基づくファイルアクセス権限チェック機能
- **Filter_Options_Extractor**: フィルタドロップダウンの選択肢を JSON ファイル群から抽出する機能
- **Pagination_Helper**: リスト型データにページネーションを適用する共通ヘルパー
- **Query_Parameter_Extractor**: HTTP リクエストからページネーション・フィルタ用クエリパラメータを抽出する共通ヘルパー
- **Template_Partial**: Jinja2 の include で再利用可能なテンプレート部品（_pagination.html, _results_table.html 等）

## 要件

### 要件 1: ファイル権限チェックの統合

**ユーザーストーリー:** 開発者として、ファイル権限チェックロジックを一箇所に集約したい。同一ロジックの重複保守を排除するため。

#### 受け入れ基準

1. THE Result_Server SHALL 単一の共通 File_Permission_Checker 関数を提供し、results.py の `check_file_permission()` と estimated.py の `_check_file_permission()` を置き換える
2. WHEN ファイル権限チェックが必要な場合、THE Route_Module SHALL 共通 File_Permission_Checker を呼び出す
3. THE File_Permission_Checker SHALL 統合前と同一の権限判定結果を返す（公開ファイルは許可、confidential タグ付きファイルは認証・所属チェックを実施）

### 要件 2: 結果一覧ルートの統合

**ユーザーストーリー:** 開発者として、results() と results_confidential() の重複ロジックを統合したい。変更時の修正漏れリスクを低減するため。

#### 受け入れ基準

1. THE Route_Module SHALL 共通の内部関数を使用して results() と results_confidential() のクエリパラメータ抽出、データ読み込み、ページ範囲外リダイレクト、テンプレートレンダリングを処理する
2. THE Route_Module SHALL results() では public_only=True、results_confidential() では public_only=False を共通関数に渡すことで動作を切り替える
3. THE Route_Module SHALL 統合前と同一の HTTP レスポンス（テンプレート、ステータスコード、リダイレクト先）を返す

### 要件 3: クエリパラメータ抽出の共通化

**ユーザーストーリー:** 開発者として、ページネーション・フィルタ用クエリパラメータの抽出ロジックを共通ヘルパーに集約したい。3箇所（results, results_confidential, estimated_results）での重複を排除するため。

#### 受け入れ基準

1. THE Result_Server SHALL Query_Parameter_Extractor を提供し、page, per_page, system, code, exp の各クエリパラメータを一括抽出する
2. THE Query_Parameter_Extractor SHALL per_page の値が許可リストに含まれない場合、デフォルト値を返す
3. WHEN クエリパラメータの抽出が必要な場合、THE Route_Module SHALL Query_Parameter_Extractor を使用する
4. THE Query_Parameter_Extractor SHALL 統合前と同一のパラメータ値を返す（page のデフォルト値 1、per_page のデフォルト値 100）

### 要件 4: フィルタマッチング関数の統合

**ユーザーストーリー:** 開発者として、`_matches_filters()` と `_matches_estimated_filters()` を統合したい。フィルタロジックの重複を排除するため。

#### 受け入れ基準

1. THE Results_Loader SHALL フィールド名マッピングをパラメータとして受け取る単一のフィルタマッチング関数を提供する
2. THE Results_Loader SHALL 通常結果では system→"system", code→"code", exp→"Exp" のマッピングを使用する
3. THE Results_Loader SHALL 推定結果では system→"benchmark_system", code→"code", exp→"exp" のマッピングを使用する
4. THE Results_Loader SHALL 統合前と同一のフィルタリング結果を返す

### 要件 5: フィルタオプション抽出関数の統合

**ユーザーストーリー:** 開発者として、`get_filter_options()` と `get_estimated_filter_options()` を統合したい。90%同一のコードの重複保守を排除するため。

#### 受け入れ基準

1. THE Results_Loader SHALL フィールド名マッピングをパラメータとして受け取る単一の Filter_Options_Extractor 関数を提供する
2. THE Filter_Options_Extractor SHALL 通常結果では system→"system", code→"code", exp→"Exp" のマッピングを使用する
3. THE Filter_Options_Extractor SHALL 推定結果では system→"benchmark_system", code→"code", exp→"exp" のマッピングを使用する
4. THE Filter_Options_Extractor SHALL 統合前と同一のフィルタオプション（systems, codes, exps の各ソート済みリスト）を返す

### 要件 6: テンプレートの重複排除

**ユーザーストーリー:** 開発者として、results.html, results_confidential.html, estimated_results.html の共通構造を統合したい。テンプレート変更時の修正漏れを防止するため。

#### 受け入れ基準

1. THE Result_Server SHALL 結果一覧ページの共通レイアウトを提供する基底テンプレートを持つ（ヘッダー、ナビゲーション、検索入力、テーブル領域を含む）
2. THE Result_Server SHALL 各結果ページ（results, results_confidential, estimated_results）のタイトル、認証警告の有無、テーブル内容を基底テンプレートのブロックとして差し替え可能にする
3. THE Result_Server SHALL estimated_results.html 内のインラインフィルタドロップダウンを _results_table.html と同様の Template_Partial として共通化する
4. THE Result_Server SHALL estimated_results.html 内のインラインページネーションコードを排除し、既存の _pagination.html を使用する
5. THE Result_Server SHALL 統合前と同一の HTML 出力を生成する（視覚的な差異がない）

### 要件 7: 不要コードの除去

**ユーザーストーリー:** 開発者として、コメントアウトされたコード・未使用インポート・未使用パラメータを除去したい。コードの可読性を向上させるため。

#### 受け入れ基準

1. THE Result_Server SHALL app.py からコメントアウトされたコード（`#app.redis = r_conn`, `#app.redis_prefix = key_prefix` 等）を除去する
2. THE Route_Module SHALL routes/estimated.py および routes/results.py から未使用の `os` モジュールインポートを除去する
3. THE Result_Server SHALL result_file.py からコメントアウトされたコード（`#SAVE_DIR`, コメントアウトされた関数シグネチャ、デバッグ用 print 文）を除去する
4. THE Result_Server SHALL 除去後もすべての既存機能が正常に動作する

### 要件 8: マジックナンバーの定数化

**ユーザーストーリー:** 開発者として、コード中に散在するマジックナンバーを名前付き定数に置き換えたい。値の意味を明確にし、変更時の一括修正を可能にするため。

#### 受け入れ基準

1. THE Results_Loader SHALL ページサイズの許可値リスト（50, 100, 200）を名前付き定数として定義する
2. THE Results_Loader SHALL デフォルトページサイズ（100）を名前付き定数として定義する
3. WHEN per_page のバリデーションが必要な場合、THE Results_Loader SHALL 定数を参照する
4. THE Route_Module SHALL per_page のバリデーションに Results_Loader の定数を参照する

### 要件 9: 管理画面のユーザーリスト準備ロジック統合

**ユーザーストーリー:** 開発者として、admin.py 内の users(), add_user(), reinvite_user() で重複するユーザーリスト準備ロジックを共通化したい。TOTP 状態付与の重複コードを排除するため。

#### 受け入れ基準

1. THE Route_Module SHALL ユーザーリスト取得と TOTP 登録状態付与を行う共通ヘルパー関数を提供する
2. WHEN ユーザーリストの表示が必要な場合、THE Route_Module SHALL 共通ヘルパー関数を使用する
3. THE Route_Module SHALL 統合前と同一のユーザーリストデータ（email, affiliations, has_totp を含む）をテンプレートに渡す
