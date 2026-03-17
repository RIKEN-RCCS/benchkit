# 要件ドキュメント: TOTP認証システム

## はじめに

BenchKit結果サーバ（Flaskアプリ）の既存Email OTP認証をTOTP（Time-based One-Time Password）認証に置き換える。Google Authenticator等のTOTPアプリを使用し、SMTP依存とGDPR懸念を排除する。管理者が招待リンクを発行し、ユーザーがQRコードをスキャンして登録するフローを採用する。ユーザー管理はRedisベースに移行し、`allowed_emails.json`ファイルを廃止する。

## 用語集

- **Result_Server**: BenchKit結果サーバ（Flask Webアプリケーション）
- **TOTP_Manager**: TOTP秘密鍵の生成・検証・QRコード生成を担当するユーティリティモジュール
- **Admin_Panel**: 管理者がユーザー管理（追加・削除・一覧・所属編集・TOTP再登録）を行うWebインターフェース
- **Auth_Router**: 認証関連のルーティングを担当するFlask Blueprint（ログイン、セットアップ、ログアウト）
- **Invitation_Token**: 管理者がユーザー追加時に生成するワンタイムURL用トークン
- **User_Store**: Redisに保存されるユーザー情報（メールアドレス、TOTP秘密鍵、所属情報）
- **Affiliation**: ユーザーに紐づく所属グループ。機密データのアクセス制御に使用
- **Confidential_Tag**: 結果ファイルに付与される機密タグ。Affiliationとの交差でアクセス可否を判定

## 要件

### 要件1: TOTP秘密鍵の管理

**ユーザーストーリー:** 開発者として、TOTP秘密鍵の生成・保存・検証を安全に行いたい。これにより、SMTP依存なしでワンタイムパスワード認証を実現できる。

#### 受入基準

1. THE TOTP_Manager SHALL `pyotp`ライブラリを使用してBase32エンコードされたTOTP秘密鍵を生成する
2. THE TOTP_Manager SHALL 指定されたメールアドレスとイシュア名を含むotpauth URI（`otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}`）を生成する
3. THE TOTP_Manager SHALL `qrcode`ライブラリを使用してotpauth URIからQRコード画像（PNG形式）を生成する
4. WHEN 6桁のTOTPコードが提出された場合、THE TOTP_Manager SHALL `pyotp`の`verify()`メソッドを使用してコードの有効性を検証する
5. THE TOTP_Manager SHALL 検証時に前後1ステップ（30秒）の時間ずれを許容する（`valid_window=1`）

### 要件2: Redisベースのユーザーストア

**ユーザーストーリー:** 管理者として、ユーザー情報をRedisで一元管理したい。これにより、JSONファイルベースの管理を廃止し、スケーラブルなユーザー管理を実現できる。

#### 受入基準

1. THE User_Store SHALL ユーザーのTOTP秘密鍵を`{prefix}:user:{email}:totp_secret`キーでRedisに保存する
2. THE User_Store SHALL ユーザーの所属情報を`{prefix}:user:{email}:affiliations`キーでRedisのリスト型として保存する
3. THE User_Store SHALL 登録済みユーザーの一覧を`{prefix}:users`キーでRedisのセット型として管理する
4. WHEN ユーザーが削除された場合、THE User_Store SHALL 該当ユーザーの全Redisキー（totp_secret、affiliations、usersセットのメンバー）を削除する
5. THE User_Store SHALL `allowed_emails.json`ファイルに依存せず、Redisのみでユーザー情報を管理する
6. THE User_Store SHALL 環境ごとのキープレフィックス（`main:`または`dev:`）を使用してデータを分離する

### 要件3: 招待リンクによるユーザー登録

**ユーザーストーリー:** 管理者として、招待リンクを発行してユーザーにTOTP登録を行わせたい。これにより、SMTP不要で安全なユーザー登録フローを実現できる。

#### 受入基準

1. WHEN 管理者がユーザーを追加した場合、THE Admin_Panel SHALL ワンタイム招待トークン（暗号学的に安全なランダム文字列）を生成する
2. THE Admin_Panel SHALL 招待トークンを`{prefix}:invitation:{token}`キーでRedisに保存し、メールアドレスと所属情報を紐づける
3. THE Admin_Panel SHALL 招待トークンに有効期限（24時間）を設定する（Redis TTL）
4. THE Admin_Panel SHALL 招待URL（`https://{host}/auth/setup/{token}`）を管理者に表示する
5. WHEN ユーザーが有効な招待URLにアクセスした場合、THE Auth_Router SHALL TOTP秘密鍵を生成し、QRコードを表示する
6. WHEN ユーザーがQRコードをスキャンし確認用TOTPコードを入力した場合、THE Auth_Router SHALL コードを検証し、検証成功時にTOTP秘密鍵をUser_Storeに保存する
7. WHEN TOTP登録が完了した場合、THE Auth_Router SHALL 使用済み招待トークンをRedisから削除する
8. IF 無効または期限切れの招待トークンでアクセスされた場合、THEN THE Auth_Router SHALL エラーメッセージを表示し、登録フローを開始しない
9. IF 既に登録済みのメールアドレスに対して招待が発行された場合、THEN THE Admin_Panel SHALL 既存のTOTP秘密鍵を上書きせず、再登録用の別フローを使用するよう管理者に通知する

### 要件4: TOTPログイン認証

**ユーザーストーリー:** ユーザーとして、メールアドレスとTOTPコードでログインしたい。これにより、メール受信を待たずに即座に認証できる。

#### 受入基準

1. WHEN ユーザーがメールアドレスを入力した場合、THE Auth_Router SHALL TOTPコード入力フォームを表示する
2. WHEN 有効なTOTPコードが入力された場合、THE Auth_Router SHALL セッションに認証状態（メールアドレス、所属情報）を保存し、認証済みページにリダイレクトする
3. IF 未登録のメールアドレスが入力された場合、THEN THE Auth_Router SHALL 登録済みアドレスと同一のレスポンスを返す（ユーザー列挙攻撃の防止）
4. IF 無効なTOTPコードが入力された場合、THEN THE Auth_Router SHALL 認証失敗メッセージを表示し、再入力を促す
5. THE Auth_Router SHALL ログアウト機能を提供し、セッションをクリアする
6. THE Auth_Router SHALL 既存のセッション管理設定（Cookie Secure、HttpOnly、SameSite、30分有効期限）を維持する

### 要件5: アクセス制御

**ユーザーストーリー:** システム管理者として、ユーザーの所属に基づいて機密データへのアクセスを制御したい。これにより、適切な権限を持つユーザーのみが機密結果を閲覧できる。

#### 受入基準

1. THE Result_Server SHALL 認証済みユーザーの所属情報と結果ファイルのConfidential_Tagの交差判定により、機密データへのアクセス可否を決定する（既存ロジックの維持）
2. WHEN ユーザーが`admin`所属を持つ場合、THE Result_Server SHALL 全ての機密データへのアクセスを許可する
3. WHEN 未認証ユーザーがアクセスした場合、THE Result_Server SHALL 公開データのみを表示する
4. THE Result_Server SHALL `/results/confidential`と`/estimated/`の両ルートで同一のアクセス制御ロジックを適用する
5. THE Result_Server SHALL URL prefix（`""`および`"/dev"`）の両環境で正しくアクセス制御を動作させる

### 要件6: 管理者パネル

**ユーザーストーリー:** 管理者として、Webインターフェースからユーザーの追加・削除・一覧表示・所属編集を行いたい。これにより、サーバーに直接アクセスせずにユーザー管理ができる。

#### 受入基準

1. WHILE ユーザーが`admin`所属で認証されている場合、THE Admin_Panel SHALL ユーザー管理インターフェースへのアクセスを許可する
2. THE Admin_Panel SHALL 登録済みユーザーの一覧（メールアドレス、所属情報、登録状態）を表示する
3. THE Admin_Panel SHALL 新規ユーザーの追加（メールアドレスと所属情報の指定）と招待リンクの生成を提供する
4. THE Admin_Panel SHALL 既存ユーザーの削除機能を提供する
5. THE Admin_Panel SHALL 既存ユーザーの所属情報の編集機能を提供する
6. THE Admin_Panel SHALL 既存ユーザーのTOTP再登録用招待リンクの生成機能を提供する（既存秘密鍵を無効化し、新しい招待を発行）
7. IF `admin`所属を持たないユーザーがAdmin_Panelにアクセスした場合、THEN THE Result_Server SHALL 403エラーを返す
8. IF 未認証ユーザーがAdmin_Panelにアクセスした場合、THEN THE Result_Server SHALL ログインページにリダイレクトする

### 要件7: 既存認証システムからの移行

**ユーザーストーリー:** 開発者として、既存のEmail OTP認証からTOTP認証にスムーズに移行したい。これにより、既存機能を壊さずに認証方式を切り替えられる。

#### 受入基準

1. THE Result_Server SHALL `utils/otp_redis_manager.py`を新しいTOTP管理モジュールに置き換える
2. THE Result_Server SHALL `utils/otp_manager.py`（ファイルベースOTP）を削除する
3. THE Result_Server SHALL `routes/results.py`と`routes/estimated.py`のOTP認証フローをTOTP認証フローに更新する
4. THE Result_Server SHALL `templates/_otp_modal.html`をTOTPログインフォームに更新する
5. THE Result_Server SHALL `app.py`のOTP Manager初期化をTOTP Manager初期化に更新する
6. THE Result_Server SHALL `config/allowed_emails.json`への依存を完全に排除する
7. THE Result_Server SHALL 認証ルートを専用のAuth Blueprint（`/auth/`プレフィックス）として分離する

### 要件8: 開発モード対応

**ユーザーストーリー:** 開発者として、Redis/TOTP不要のローカル開発モードを維持したい。これにより、外部依存なしでUIの開発・テストができる。

#### 受入基準

1. THE Result_Server SHALL `app_dev.py`にTOTP認証のスタブモジュールを提供する
2. WHILE 開発モードで実行されている場合、THE Result_Server SHALL 任意のメールアドレスとTOTPコードで認証を成功させる
3. WHILE 開発モードで実行されている場合、THE Result_Server SHALL Redis接続を不要とする
4. THE Result_Server SHALL 開発モードのスタブが本番コードと同一のインターフェースを持つことを保証する

### 要件9: ナビゲーションの更新

**ユーザーストーリー:** ユーザーとして、認証状態に応じた適切なナビゲーションを表示したい。これにより、ログイン・ログアウト・管理パネルへのアクセスが直感的になる。

#### 受入基準

1. WHILE ユーザーが認証済みの場合、THE Result_Server SHALL ナビゲーションにログアウトリンクとユーザーのメールアドレスを表示する
2. WHILE ユーザーが未認証の場合、THE Result_Server SHALL ナビゲーションにログインリンクを表示する
3. WHILE ユーザーが`admin`所属で認証されている場合、THE Result_Server SHALL ナビゲーションに管理パネルへのリンクを表示する
4. THE Result_Server SHALL `_navigation.html`テンプレートを更新して認証状態を反映する
