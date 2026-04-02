# 要件定義書

## はじめに

BenchKitフレームワークにおいて、ベンチマーク結果と使用されたソースコードの紐付けを実現する機能。現在、結果JSONの`code`フィールドにはプログラム名のみが記録されており、実際にビルドに使用されたソースコードのリポジトリURL、ブランチ名、コミットハッシュ、またはアーカイブファイルのmd5sumが記録されていない。本機能により、ベンチマーク結果の再現性とトレーサビリティを向上させる。

## 用語集

- **BenchKit**: CIベンチマークフレームワーク全体のシステム名
- **Result_JSON**: ベンチマーク実行結果を格納するJSONファイル（`result_server/_dev_data/main/received/` 配下に保存）
- **Build_Script**: 各プログラムのビルド手順を定義するシェルスクリプト（`programs/<code>/build.sh`）
- **Result_Server**: Flask製のWebアプリケーションで、結果テーブルを表示するサーバー
- **Results_Table**: Result_Serverが表示するHTML結果一覧テーブル（`_results_table.html`）
- **bk_functions**: ベンチマーク結果出力の標準化関数群を提供するシェルスクリプト（`scripts/bk_functions.sh`）
- **result_sh**: 実行出力を解析してResult_JSONを生成するスクリプト（`scripts/result.sh`）
- **source_info**: Result_JSONに追加されるソースコード追跡情報のオブジェクト
- **source_type**: ソースコードの取得方法を示す識別子（`git` または `file`）
- **short_commit_hash**: gitコミットハッシュの先頭7桁
- **short_md5sum**: md5sumの先頭8桁

## 要件

### 要件 1: JSONデータ形式の拡張

**ユーザーストーリー:** ベンチマーク管理者として、結果JSONにソースコード追跡情報を含めたい。これにより、各ベンチマーク結果がどのコードバージョンで実行されたかを正確に特定できるようにする。

#### 受入基準

1. THE result_sh SHALL Result_JSONに `source_info` オブジェクトを含める
2. WHEN source_type が `git` の場合、THE source_info SHALL `source_type`、`repo_url`、`branch`、`commit_hash` フィールドを含む
3. WHEN source_type が `file` の場合、THE source_info SHALL `source_type`、`file_path`、`md5sum` フィールドを含む
4. WHEN source_info が提供されない場合、THE result_sh SHALL `source_info` フィールドを `null` として出力する
5. THE commit_hash SHALL gitコミットハッシュの完全な40桁の文字列を格納する
6. THE md5sum SHALL md5sumの完全な32桁の文字列を格納する

### 要件 2: bk_functions ヘルパー関数の追加

**ユーザーストーリー:** ベンチマークプログラム開発者として、Build_Script内でソースコードの取得とメタデータ収集を単一の標準化された関数で行いたい。これにより、覚える関数を最小限にし、参入コストを下げる。

#### 受入基準

1. THE bk_functions SHALL `bk_fetch_source` 関数を提供する。シグネチャは `bk_fetch_source <source> <dest_dir> [branch]` とする
2. WHEN 第1引数が `http://` または `https://` で始まるか `.git` で終わる場合、THE bk_fetch_source SHALL git clone として動作する
3. WHEN 第1引数がそれ以外の場合、THE bk_fetch_source SHALL ファイルアーカイブ（tar.gz/tgz）の展開として動作する
4. WHEN git clone として動作する場合、THE bk_fetch_source SHALL 環境変数 `BK_SOURCE_TYPE` に `git` を、`BK_REPO_URL` にリポジトリURLを、`BK_BRANCH` にブランチ名を、`BK_COMMIT_HASH` にHEADのコミットハッシュ完全版を設定する。加えて、同じ情報を `results/source_info.env` ファイルにエクスポート形式で書き出す
5. WHEN 第3引数（branch）が指定された場合、THE bk_fetch_source SHALL `git clone --branch <branch>` を実行する。省略時はデフォルトブランチを使用する
6. WHEN ファイルアーカイブとして動作する場合、THE bk_fetch_source SHALL 環境変数 `BK_SOURCE_TYPE` に `file` を、`BK_FILE_PATH` にアーカイブファイルパスを、`BK_MD5SUM` にアーカイブファイルのmd5sum完全版を設定する。加えて、同じ情報を `results/source_info.env` ファイルにエクスポート形式で書き出す
7. IF git clone が失敗した場合、THEN THE bk_fetch_source SHALL 標準エラー出力にエラーメッセージを出力し、戻り値1を返す
8. IF 指定されたアーカイブファイルが存在しない場合、THEN THE bk_fetch_source SHALL 標準エラー出力にエラーメッセージを出力し、戻り値1を返す
9. THE bk_fetch_source SHALL 既にクローン済みのディレクトリが存在する場合、再クローンをスキップし、既存ディレクトリからメタデータを取得する

### 要件 3: ソース追跡メタデータの結果JSONへの自動統合

**ユーザーストーリー:** ベンチマーク管理者として、build.shで `bk_fetch_source` を使うだけで、ソース追跡メタデータが自動的にResult_JSONに組み込まれるようにしたい。アプリ開発者がrun.shで追加の関数呼び出しをする必要はない。

#### 受入基準

1. THE result_sh SHALL `results/source_info.env` ファイルが存在する場合、これを読み込み Result_JSON の `source_info` オブジェクトに変換する
2. WHEN `results/source_info.env` に `BK_SOURCE_TYPE=git` が含まれる場合、THE result_sh SHALL `BK_REPO_URL`、`BK_BRANCH`、`BK_COMMIT_HASH` の値から git 型の `source_info` オブジェクトを構築する
3. WHEN `results/source_info.env` に `BK_SOURCE_TYPE=file` が含まれる場合、THE result_sh SHALL `BK_FILE_PATH`、`BK_MD5SUM` の値から file 型の `source_info` オブジェクトを構築する
4. WHEN `results/source_info.env` ファイルが存在しない場合、THE result_sh SHALL `source_info` を `null` として出力する
5. THE アプリ開発者 SHALL run.sh 内でソース追跡に関する追加の関数呼び出しを行う必要がない

### 要件 4: 結果テーブルでのソースコード情報表示

**ユーザーストーリー:** ベンチマーク利用者として、結果テーブルのCODE列からソースコードの場所に直接アクセスしたい。また、ブランチ名やコミットハッシュ（またはmd5sum）をテーブル上で確認したい。

#### 受入基準

1. WHEN source_info の source_type が `git` の場合、THE Results_Table SHALL CODE列の値をリポジトリURLへのハイパーリンクとして表示する
2. WHEN source_info の source_type が `file` の場合、THE Results_Table SHALL CODE列の値にファイルパスをツールチップとして表示する
3. THE Results_Table SHALL 「Branch/Hash」列を追加し、gitの場合はブランチ名とshort_commit_hashを、fileの場合はshort_md5sumを表示する
4. WHEN source_info が `null` の場合、THE Results_Table SHALL CODE列を現在と同じプレーンテキストとして表示し、「Branch/Hash」列にはハイフン（`-`）を表示する
5. THE short_commit_hash SHALL commit_hashの先頭7桁を表示する
6. THE short_md5sum SHALL md5sumの先頭8桁を表示する

### 要件 5: results_loader のデータ処理拡張

**ユーザーストーリー:** 開発者として、results_loaderがsource_info情報を正しく読み込み、テーブル行データに含めるようにしたい。これにより、テンプレート側でソース追跡情報を利用できるようになる。

#### 受入基準

1. THE results_loader SHALL Result_JSONから `source_info` フィールドを読み込み、テーブル行データに含める
2. WHEN Result_JSONに `source_info` フィールドが存在しない場合、THE results_loader SHALL `source_info` を `None` としてテーブル行データに設定する
3. THE results_loader SHALL columns定義に `("Branch/Hash", "source_hash")` を追加する

### 要件 6: 後方互換性の維持

**ユーザーストーリー:** ベンチマーク管理者として、既存のResult_JSONファイルが新しいシステムでも正常に表示されることを保証したい。

#### 受入基準

1. WHEN 既存のResult_JSONに `source_info` フィールドが存在しない場合、THE Result_Server SHALL エラーなく結果を表示する
2. THE result_sh SHALL 既存の `results/result` 形式（SOURCE_INFO行なし）を引き続き正常に処理する
3. WHEN Build_Scriptが `bk_fetch_source` を使用しない場合、THE BenchKit SHALL 既存の動作を変更せずにベンチマークを実行する
