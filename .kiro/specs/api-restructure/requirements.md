# 要件ドキュメント

## はじめに

BenchKit結果サーバ（result_server）のAPIルート名称を統一し、パス構造を合理的に再配置するリファクタリング。現在のAPIは名称の不統一（`write-api`, `write-est`, `upload-tgz`）、データ受信用Blueprintの不要な分離、APIエンドポイントとページルートの区別の欠如、SAVE_DIRのモジュールレベル変数管理の煩雑さといった問題を抱えている。本リファクタリングでは、これらを解消し、一貫性のあるAPI設計に改善する。

## 本番環境の構成

- systemdで起動: `gunicorn -w 2 -b 127.0.0.1:8800 benchkit.result_server.app:app`
- `WorkingDirectory=/home/nakamura/fugakunext/main`
- `BASE_PATH=/home/nakamura/fugakunext`
- ディレクトリ構成: `main/` 配下に `benchkit/`, `config/`, `estimated_results/`, `flask_session/`, `received/`
- `config/allowed_emails.json` が1ファイルのみ存在

## APIクライアント

- `scripts/send_results.sh`: CI/CDから `/write-api` と `/upload-tgz` を呼び出し
- BenchPark CI (`benchpark-bridge/scripts/ci_generator.sh`) も同じ `send_results.sh` を使用
- `/write-est` を呼び出すクライアントスクリプトはリポジトリ内に存在しない（外部利用の可能性あり）

## 用語集

- **Result_Server**: BenchKit結果サーバ。Flask Blueprintで構成されたWebアプリケーション
- **Ingest_API**: データ受信用APIエンドポイント群（結果JSON、推定結果JSON、PA Dataの受信）
- **Results_View**: 結果表示用ページルート群（一覧、詳細、比較、機密結果）
- **Estimated_View**: 推定結果表示用ページルート群（一覧、個別表示）
- **Blueprint**: Flaskのルートグループ化機構
- **SAVE_DIR**: 受信した結果JSONおよびPA Dataの保存ディレクトリ（`received/`）
- **ESTIMATED_DIR**: 受信した推定結果JSONの保存ディレクトリ（`estimated_results/`）
- **CI_Client**: CI/CDパイプラインからAPIを呼び出すスクリプト（`scripts/send_results.sh`）

## 要件

### 要件1: APIエンドポイントの命名統一

**ユーザーストーリー:** 開発者として、APIエンドポイント名から機能が一目で分かるようにしたい。APIの管理・ドキュメント化が容易になるため。

#### 受け入れ基準

1. THE Ingest_API SHALL 全てのデータ取り込みエンドポイントを `/api/ingest/` プレフィックス配下に配置する
2. WHEN 結果JSONを受信する場合、THE Ingest_API SHALL `POST /api/ingest/result` でリクエストを受け付ける（旧: `/write-api`）
3. WHEN 推定結果JSONを受信する場合、THE Ingest_API SHALL `POST /api/ingest/estimate` でリクエストを受け付ける（旧: `/write-est`）
4. WHEN PA Data（tgz）をアップロードする場合、THE Ingest_API SHALL `POST /api/ingest/padata` でリクエストを受け付ける（旧: `/upload-tgz`）
5. THE Ingest_API SHALL 各エンドポイントのレスポンス形式を変更せず維持する

### 要件2: データ受信Blueprintの統合

**ユーザーストーリー:** 開発者として、データ受信に関するルートを1つのBlueprintにまとめたい。コードの見通しが良くなり保守性が向上するため。

#### 受け入れ基準

1. THE Result_Server SHALL `receive_bp`と`upload_bp`を1つのBlueprint（`api_bp`）に統合する
2. THE Result_Server SHALL 統合後のBlueprintを `routes/api.py` に配置する
3. THE Result_Server SHALL 統合後も全てのデータ受信機能（結果JSON受信、推定結果JSON受信、PA Dataアップロード）を維持する
4. THE Result_Server SHALL APIキー認証ロジックを統合Blueprint内で共通化する

### 要件3: 後方互換性の維持

**ユーザーストーリー:** 運用担当者として、APIリファクタリング後も既存のCI/CDパイプラインが正常に動作し続けることを保証したい。

#### 受け入れ基準

1. THE Result_Server SHALL 旧パス（`/write-api`, `/write-est`, `/upload-tgz`）へのリクエストを新パス（`/api/ingest/result`, `/api/ingest/estimate`, `/api/ingest/padata`）と同一の処理で受け付ける互換ルートとして維持する
2. WHEN CI_Clientが旧パスにリクエストを送信した場合、THE Result_Server SHALL 正常にリクエストを処理し同一のレスポンスを返す
3. THE Result_Server SHALL 旧パスの互換ルートにアクセスがあった場合、非推奨（deprecated）であることをログ出力する
4. THE CI_Client（`scripts/send_results.sh`）SHALL 新しいAPIパスを使用するよう更新する

### 要件4: SAVE_DIR管理の改善

**ユーザーストーリー:** 開発者として、保存ディレクトリの設定をFlask app.configで一元管理したい。開発環境でのオーバーライドが簡潔になるため。

#### 受け入れ基準

1. THE Result_Server SHALL SAVE_DIRとESTIMATED_DIRをFlaskの`app.config`（`RECEIVED_DIR`, `ESTIMATED_DIR`）から取得する
2. THE Result_Server SHALL 各ルートモジュールでモジュールレベル変数としてSAVE_DIRを定義しない
3. WHEN ルートハンドラがディレクトリパスを必要とする場合、THE Result_Server SHALL `current_app.config`から取得する
4. THE Result_Server SHALL `utils/results_loader.py`のSAVE_DIR・ESTIMATED_DIRもapp.configから取得する方式に変更する
5. THE Result_Server SHALL 開発用起動スクリプト（`app_dev.py`）でのモジュール変数直接書き換えを不要にする

### 要件5: ページルートのパス整理

**ユーザーストーリー:** ユーザーとして、URLの構造が直感的で一貫性があることを期待する。ページ間のナビゲーションが分かりやすくなるため。

#### 受け入れ基準

1. THE Results_View SHALL `/results/` 配下のパス構造を維持する（`/results/`, `/results/confidential`, `/results/compare`, `/results/detail/<filename>`, `/results/<filename>`）
2. THE Estimated_View SHALL `/estimated/` をURLプレフィックスとして使用する（`/estimated_results/` から短縮）
3. THE Navigation SHALL 新しいURLパスに合わせてリンクを更新する
4. THE Result_Server SHALL `app.py`のBlueprint登録で新しいプレフィックスを使用する

### 要件6: 不要ファイルの整理

**ユーザーストーリー:** 開発者として、リファクタリング後に不要になった旧ルートファイルを削除したい。コードベースの整理のため。

#### 受け入れ基準

1. WHEN Blueprint統合が完了した場合、THE Result_Server SHALL `routes/receive.py`と`routes/upload_tgz.py`を削除する
2. THE Result_Server SHALL 新しい`routes/api.py`が全てのデータ受信機能を含むことを確認する

### 要件7: テストの更新

**ユーザーストーリー:** 開発者として、リファクタリング後も全てのテストが通ることを保証したい。

#### 受け入れ基準

1. THE Result_Server SHALL 既存テスト（25テスト）がリファクタリング後も全て通過する
2. WHEN 新しいAPIパスが追加された場合、THE Result_Server SHALL 新パスに対するテストを追加する
3. WHEN 旧パスの互換ルートが存在する場合、THE Result_Server SHALL 旧パスへのリクエストが正常に処理されることをテストする

## 正当性プロパティ

### P1: APIパス一貫性
全てのデータ受信エンドポイントは `/api/` プレフィックスで始まること。

### P2: 後方互換性
旧パス（`/write-api`, `/write-est`, `/upload-tgz`）へのリクエストは、新パスと同一のレスポンスを返すこと。

### P3: ディレクトリ設定の一元性
全てのルートモジュールとユーティリティモジュールが `current_app.config` からディレクトリパスを取得し、モジュールレベル変数に依存しないこと。

### P4: 機能保全
リファクタリング前後で、全てのAPI機能（結果受信、推定結果受信、PA Dataアップロード、結果表示、比較、詳細表示）が同一の動作をすること。
