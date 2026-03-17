# 実装計画: TOTP認証システム

## 概要

BenchKit結果サーバのEmail OTP認証をTOTP認証に移行する。`totp_manager`と`user_store`のコアモジュールから段階的に実装し、認証・管理Blueprint、テンプレート更新、既存コードの移行、開発モード対応の順に進める。各ステップで前のステップの成果物を利用し、最終的に全コンポーネントを統合する。

## タスク

- [x] 1. コアユーティリティモジュールの実装
  - [x] 1.1 `result_server/utils/totp_manager.py`を作成する
    - `generate_secret()`: `pyotp.random_base32()`でBase32秘密鍵を生成
    - `generate_totp_uri(secret, email, issuer)`: otpauth URIを生成
    - `generate_qr_base64(secret, email, issuer)`: QRコード画像をBase64 PNG文字列で返す
    - `verify_code(secret, code)`: `pyotp.TOTP(secret).verify(code, valid_window=1)`で検証
    - `ISSUER_NAME = "BenchKit"`定数を定義
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.2 `result_server/tests/test_totp_manager.py`にProperty 1のプロパティテストを作成する
    - **Property 1: TOTP検証ラウンドトリップ**
    - 任意の生成された秘密鍵に対して、`pyotp.TOTP(secret).now()`で生成したコードが`verify_code()`で検証成功することを確認
    - **Validates: Requirements 1.1, 1.4, 1.5**

  - [ ]* 1.3 `result_server/tests/test_totp_manager.py`にProperty 2のプロパティテストを作成する
    - **Property 2: otpauth URI構造の正当性**
    - 任意のメールアドレス・イシュア名に対して、URIが`otpauth://totp/`で始まり、パラメータを正しく含むことを確認
    - QRコード出力が`data:image/png;base64,`で始まることを確認
    - **Validates: Requirements 1.2, 1.3**

  - [x] 1.4 `result_server/utils/user_store.py`を作成する
    - `UserStore`クラス: `__init__(redis_conn, key_prefix)`
    - ユーザー管理: `create_user()`, `get_user()`, `delete_user()`, `list_users()`, `update_affiliations()`, `user_exists()`, `get_affiliations()`, `clear_totp_secret()`, `has_totp_secret()`
    - 招待トークン管理: `create_invitation()`, `get_invitation()`, `delete_invitation()`
    - `get_user_store()`ヘルパー関数（`current_app.config["USER_STORE"]`からインスタンス取得）
    - Redisキー構造: `{prefix}:users`(Set), `{prefix}:user:{email}:totp_secret`(String), `{prefix}:user:{email}:affiliations`(List), `{prefix}:invitation:{token}`(Hash, TTL 24h)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3_

  - [ ]* 1.5 `result_server/tests/test_user_store.py`にProperty 3のプロパティテストを作成する
    - **Property 3: ユーザー作成ラウンドトリップ**
    - `fakeredis`を使用。任意のメールアドレス・秘密鍵・所属リストで`create_user()`後、`get_user()`で取得したデータが一致することを確認
    - **Validates: Requirements 2.1, 2.2, 2.3**

  - [ ]* 1.6 `result_server/tests/test_user_store.py`にProperty 4のプロパティテストを作成する
    - **Property 4: ユーザー削除の完全性**
    - 任意の登録済みユーザーに対して、`delete_user()`後に`get_user()`がNone、`user_exists()`がFalse、`get_affiliations()`が空リストを返すことを確認
    - **Validates: Requirements 2.4**

  - [ ]* 1.7 `result_server/tests/test_user_store.py`にProperty 5のプロパティテストを作成する
    - **Property 5: キープレフィックスによるデータ分離**
    - `"main:"`と`"dev:"`の2つのUserStoreで、一方に登録したユーザーが他方から参照できないことを確認
    - **Validates: Requirements 2.6**

  - [ ]* 1.8 `result_server/tests/test_user_store.py`にProperty 6のプロパティテストを作成する
    - **Property 6: 招待トークンラウンドトリップ**
    - 任意のメールアドレス・所属リストで`create_invitation()`後、`get_invitation()`で取得したデータが一致し、トークンが32文字以上で一意であることを確認
    - **Validates: Requirements 3.1, 3.2**

- [x] 2. チェックポイント - コアモジュールの検証
  - 全テストが通ることを確認し、不明点があればユーザーに質問する。

- [x] 3. 認証Blueprintの実装
  - [x] 3.1 `result_server/routes/auth.py`を作成する
    - `auth_bp = Blueprint("auth", __name__, url_prefix="/auth")`
    - `login()`: GET→ログインフォーム表示、POST(emailのみ)→TOTPコード入力フォーム表示、POST(email+totp_code)→認証処理
    - 認証成功時: セッションに`authenticated`, `user_email`, `user_affiliations`を保存
    - 未登録メールアドレスでも同一レスポンスを返す（ユーザー列挙攻撃防止）
    - `setup(token)`: GET→招待トークン検証+QRコード表示、POST→TOTPコード検証+ユーザー登録+トークン削除
    - 無効/期限切れトークンでエラーメッセージ表示
    - `logout()`: セッションクリア後リダイレクト
    - _Requirements: 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 3.2 `result_server/templates/auth_login.html`を作成する
    - メールアドレス入力フォーム（ステップ1）
    - TOTPコード入力フォーム（ステップ2、メールアドレス送信後に表示）
    - Flashメッセージ表示エリア
    - 全てのユーザー向けテキストは英語で記述
    - _Requirements: 4.1, 4.4_

  - [x] 3.3 `result_server/templates/auth_setup.html`を作成する
    - QRコード画像表示（Base64 PNG）
    - 秘密鍵の手動入力用テキスト表示
    - 確認用TOTPコード入力フォーム
    - 全てのユーザー向けテキストは英語で記述
    - _Requirements: 3.5, 3.6_

  - [ ]* 3.4 `result_server/tests/test_auth.py`にProperty 7のプロパティテストを作成する
    - **Property 7: ユーザー列挙攻撃の防止**
    - Flaskテストクライアント + `fakeredis`を使用。任意のメールアドレス（登録済み・未登録）でログインPOSTした場合のHTTPステータスコードが同一であることを確認
    - **Validates: Requirements 4.3**

  - [ ]* 3.5 `result_server/tests/test_auth.py`にユニットテストを作成する
    - 有効な招待URLでQRコードが表示されること（要件3.5）
    - セットアップ完了後に招待トークンが削除されること（要件3.7）
    - 無効/期限切れトークンでエラーが表示されること（要件3.8）
    - ログアウト後にセッションがクリアされること（要件4.5）
    - _Requirements: 3.5, 3.7, 3.8, 4.5_

- [x] 4. 管理者Blueprintの実装
  - [x] 4.1 `result_server/routes/admin.py`を作成する
    - `admin_bp = Blueprint("admin", __name__, url_prefix="/admin")`
    - `admin_required`デコレータ: 未認証→ログインリダイレクト、非admin→403
    - `users()`: ユーザー一覧表示（メールアドレス、所属、TOTP登録状態）
    - `add_user()`: ユーザー追加+招待トークン生成+招待URL表示。既に登録済みの場合は再登録フローを案内
    - `delete_user(email)`: ユーザー削除
    - `update_affiliations(email)`: 所属情報更新
    - `reinvite_user(email)`: TOTP再登録用招待リンク生成（既存秘密鍵を無効化）
    - _Requirements: 3.1, 3.2, 3.4, 3.9, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x] 4.2 `result_server/templates/admin_users.html`を作成する
    - ユーザー一覧テーブル（メールアドレス、所属、登録状態）
    - ユーザー追加フォーム（メールアドレス、所属情報入力）
    - 招待URL表示エリア
    - 各ユーザーの削除・所属編集・再招待ボタン
    - 全てのユーザー向けテキストは英語で記述
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 4.3 `result_server/tests/test_admin.py`にProperty 9のプロパティテストを作成する
    - **Property 9: 管理者権限チェック**
    - Flaskテストクライアントを使用。任意の非admin所属ユーザーでAdmin_Panelの全エンドポイントにアクセスした場合、403が返ることを確認
    - **Validates: Requirements 6.7**

  - [ ]* 4.4 `result_server/tests/test_admin.py`にユニットテストを作成する
    - 登録済みメールアドレスへの招待で適切な通知が返ること（要件3.9）
    - 未認証ユーザーがAdmin_Panelにアクセスするとログインにリダイレクトされること（要件6.8）
    - _Requirements: 3.9, 6.8_

- [x] 5. チェックポイント - Blueprint検証
  - 全テストが通ることを確認し、不明点があればユーザーに質問する。

- [x] 6. 既存コードの移行とアクセス制御統合
  - [x] 6.1 `result_server/app.py`を更新する
    - `otp_redis_manager`のインポートと初期化を削除
    - `UserStore`のインポートと初期化を追加（`app.config["USER_STORE"] = UserStore(r_conn, key_prefix)`）
    - `auth_bp`と`admin_bp`のBlueprint登録を追加（URL prefixを考慮）
    - _Requirements: 7.1, 7.5_

  - [x] 6.2 `result_server/routes/results.py`を更新する
    - OTP認証フロー（`otp_redis_manager`使用箇所）をセッションベースのアクセス制御に置き換え
    - セッションキーを統一（`authenticated`, `user_email`, `user_affiliations`）
    - `user_store.get_affiliations()`を使用したConfidential_Tag交差判定
    - OTPモーダル関連のテンプレート変数を削除
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 7.3_

  - [x] 6.3 `result_server/routes/estimated.py`を更新する
    - `results.py`と同様のアクセス制御更新を適用
    - セッションキーの統一とOTPモーダル関連の削除
    - _Requirements: 5.1, 5.4, 5.5, 7.3_

  - [ ]* 6.4 `result_server/tests/test_auth.py`にProperty 8のプロパティテストを追加する
    - **Property 8: アクセス制御の交差判定**
    - 任意の所属リストとConfidential_Tagリストに対して、交差が空でなければアクセス許可、空ならアクセス拒否。`admin`所属は常にアクセス許可
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 7. テンプレート更新と旧ファイル削除
  - [x] 7.1 `result_server/templates/_navigation.html`を更新する
    - 認証済み: ユーザーメールアドレス表示、ログアウトリンク
    - 未認証: ログインリンク
    - admin所属: 管理パネルリンク追加
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 7.2 `result_server/templates/results_confidential.html`を更新する
    - OTPモーダルの呼び出しを削除
    - 未認証時にログインページへのリンクを表示
    - _Requirements: 7.4_

  - [x] 7.3 `result_server/templates/estimated_results.html`を更新する
    - OTPモーダルの呼び出しを削除
    - 未認証時にログインページへのリンクを表示
    - _Requirements: 7.4_

  - [x] 7.4 旧ファイルを削除する
    - `result_server/utils/otp_manager.py`を削除
    - `result_server/templates/_otp_modal.html`を削除
    - _Requirements: 7.2, 7.4_

- [x] 8. 開発モード対応
  - [x] 8.1 `result_server/app_dev.py`を更新する
    - `_create_stub_totp_manager()`: TOTP検証を常に成功させるスタブモジュール作成
    - `_create_stub_user_store()`: Redis不要のインメモリUserStoreスタブ作成（`get_affiliations()`は常に`["dev", "admin"]`を返す）
    - 既存のOTPスタブを新しいTOTP/UserStoreスタブに置き換え
    - スタブが本番コードと同一のインターフェースを持つことを保証
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 8.2 `result_server/tests/test_totp_manager.py`にProperty 10のプロパティテストを追加する
    - **Property 10: 開発モードでの認証バイパス**
    - 任意のメールアドレスとTOTPコードに対して、スタブ`verify_code()`が常にTrueを返すことを確認
    - **Validates: Requirements 8.2**

  - [ ]* 8.3 `result_server/tests/test_totp_manager.py`にProperty 11のプロパティテストを追加する
    - **Property 11: スタブと本番のインターフェース互換性**
    - `totp_manager`の公開関数名とスタブモジュールの関数名が一致することを確認
    - `UserStore`の公開メソッド名とスタブの公開メソッド名が一致することを確認
    - **Validates: Requirements 8.4**

- [ ] 9. ナビゲーションのユニットテスト
  - [ ]* 9.1 `result_server/tests/test_auth.py`にナビゲーション表示のユニットテストを追加する
    - 認証済みユーザーのナビゲーションにログアウトリンクが表示されること（要件9.1）
    - 未認証ユーザーのナビゲーションにログインリンクが表示されること（要件9.2）
    - adminユーザーのナビゲーションに管理パネルリンクが表示されること（要件9.3）
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 10. 最終チェックポイント - 全体統合検証
  - 全テストが通ることを確認し、不明点があればユーザーに質問する。

## 備考

- `*`マーク付きのタスクはオプションで、MVP実装時にはスキップ可能
- 各タスクは特定の要件を参照しており、トレーサビリティを確保
- チェックポイントで段階的な検証を実施
- プロパティテストは正当性プロパティの機械的検証を提供
- ユニットテストは具体的なシナリオとエッジケースを検証
- テストには`fakeredis`を使用してRedis依存を排除
- 全てのユーザー向けメッセージ（Flash、エラー、UIテキスト）は英語で記述すること
