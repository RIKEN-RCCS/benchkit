# 要件ドキュメント: 結果一覧ページネーション

## はじめに

ベンチマーク結果のJSONファイルが1万件以上に増加した場合、結果一覧ページ（`/results/`、`/results/confidential`、`/estimated/`）の表示速度が低下し、ページが縦に非常に長くなる。本機能はサーバーサイドページネーションを導入し、大量データ環境でのスケーラビリティを確保する。

## 用語集

- **Result_Server**: Flaskベースのベンチマーク結果表示Webアプリケーション
- **Results_Loader**: JSONファイルをディスクから読み込み、テーブル行データに変換するユーティリティモジュール（`results_loader.py`）
- **Pagination_Controls**: ページ番号、前へ/次へボタンなどのページ遷移UI要素
- **Page_Size**: 1ページあたりに表示する結果の件数
- **Current_Page**: 現在表示中のページ番号（1始まり）
- **Total_Pages**: 全結果件数とPage_Sizeから算出される総ページ数
- **Results_Page**: `/results/`（公開結果一覧）ページ
- **Confidential_Page**: `/results/confidential`（認証付き機密結果一覧）ページ
- **Estimated_Page**: `/estimated/`（推定結果一覧）ページ
- **Filter**: SYSTEM、CODE、Expなどのドロップダウンによる絞り込み機能

## 要件

### 要件 1: サーバーサイドページネーション

**ユーザーストーリー:** 開発者として、結果一覧ページにページネーションを導入したい。大量のJSONファイルがある場合でもページの読み込みが高速になるようにするため。

#### 受け入れ基準

1. WHEN Current_Page パラメータがクエリ文字列で指定された場合、THE Results_Loader SHALL 指定ページに該当する結果のみを読み込み対象として返却する
2. WHEN Current_Page パラメータが指定されていない場合、THE Results_Loader SHALL 1ページ目の結果を返却する
3. THE Results_Loader SHALL Page_Size のデフォルト値を100件とする
4. WHEN Current_Page が1未満またはTotal_Pagesを超える値の場合、THE Result_Server SHALL 有効な範囲内のページ（1ページ目または最終ページ）にリダイレクトする

### 要件 2: ページネーションUIコントロール

**ユーザーストーリー:** ユーザーとして、結果一覧ページでページ間を簡単に移動したい。目的のデータに素早くアクセスできるようにするため。

#### 受け入れ基準

1. THE Pagination_Controls SHALL 現在のページ番号と総ページ数を「Page X of Y」形式で表示する
2. WHEN 前のページが存在する場合、THE Pagination_Controls SHALL 「Previous」ボタンを有効な状態で表示する
3. WHEN 次のページが存在する場合、THE Pagination_Controls SHALL 「Next」ボタンを有効な状態で表示する
4. WHEN 前のページが存在しない場合、THE Pagination_Controls SHALL 「Previous」ボタンを無効な状態で表示する
5. WHEN 次のページが存在しない場合、THE Pagination_Controls SHALL 「Next」ボタンを無効な状態で表示する
6. THE Pagination_Controls SHALL 先頭ページへの「First」リンクと末尾ページへの「Last」リンクを表示する
7. THE Pagination_Controls SHALL テーブルの上部と下部の両方に表示する

### 要件 3: 全対象ページへの適用

**ユーザーストーリー:** ユーザーとして、全ての結果一覧ページで一貫したページネーション体験を得たい。どのページでも同じ操作方法でデータを閲覧できるようにするため。

#### 受け入れ基準

1. THE Results_Page SHALL ページネーション機能を備える
2. THE Confidential_Page SHALL ページネーション機能を備える
3. THE Estimated_Page SHALL ページネーション機能を備える
4. THE Pagination_Controls SHALL 全対象ページで同一のUI構造を使用する

### 要件 4: フィルタとページネーションの連携

**ユーザーストーリー:** ユーザーとして、フィルタ条件を適用した状態でページネーションを利用したい。絞り込んだ結果セットの中でページ移動できるようにするため。

#### 受け入れ基準

1. WHEN Filter が適用された場合、THE Results_Loader SHALL フィルタ条件に一致する結果のみを対象としてページネーションを適用する
2. WHEN Filter が変更された場合、THE Pagination_Controls SHALL Current_Page を1にリセットする
3. WHEN ページ遷移が行われた場合、THE Pagination_Controls SHALL 適用中のFilter条件をクエリ文字列に保持する
4. THE Pagination_Controls SHALL フィルタ適用後の総件数を表示する

### 要件 5: 表示件数の変更

**ユーザーストーリー:** ユーザーとして、1ページあたりの表示件数を変更したい。自分の閲覧スタイルに合わせてデータ量を調整できるようにするため。

#### 受け入れ基準

1. THE Pagination_Controls SHALL 表示件数の選択肢として 50、100、200 を提供する
2. WHEN 表示件数が変更された場合、THE Pagination_Controls SHALL Current_Page を1にリセットする
3. WHEN 表示件数が変更された場合、THE Result_Server SHALL 選択された件数に基づいてTotal_Pagesを再計算する

### 要件 6: 既存機能との互換性

**ユーザーストーリー:** 開発者として、ページネーション導入後も既存の機能が正常に動作することを保証したい。リグレッションを防止するため。

#### 受け入れ基準

1. THE Results_Page SHALL キーワード検索フィルタ機能を維持する
2. THE Results_Page SHALL Compare（比較）チェックボックス機能を維持する
3. THE Confidential_Page SHALL 認証状態に基づくアクセス制御を維持する
4. THE Estimated_Page SHALL 認証状態に基づくアクセス制御を維持する
5. WHEN Compare ボタンが押された場合、THE Result_Server SHALL 現在のページで選択されたチェックボックスの結果のみを比較対象とする

### 要件 7: ページネーション計算の正確性

**ユーザーストーリー:** 開発者として、ページネーションの計算ロジックが正確であることを保証したい。全ての結果が漏れなく表示されるようにするため。

#### 受け入れ基準

1. FOR ALL 有効な Page_Size と結果総数の組み合わせ、THE Results_Loader SHALL 全ての結果がいずれかのページに含まれることを保証する（結果の欠落がない）
2. FOR ALL 有効な Page_Size と結果総数の組み合わせ、THE Results_Loader SHALL 同一の結果が複数ページに重複して表示されないことを保証する
3. THE Results_Loader SHALL Total_Pages を ceil(総件数 / Page_Size) として計算する
4. WHEN 結果が0件の場合、THE Results_Loader SHALL Total_Pages を1として返却し、空のテーブルを表示する
