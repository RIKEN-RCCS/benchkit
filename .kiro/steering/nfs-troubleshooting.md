---
inclusion: fileMatch
fileMatchPattern: 'scripts/wait_for_nfs.sh|scripts/result.sh|scripts/matrix_generate.sh'
---

# NFS同期問題トラブルシューティング履歴

MiyabiG/MiyabiCでのNFS同期問題に関する対策履歴と知見をまとめています。

## 問題の症状
- 計算ノードで作成された`results/*.json`ファイルがログインノードから見えない
- 120-180秒待機してもファイルが同期されない
- 0バイトファイルが保存される現象（過去に発生）
- GitLab CIのアーティファクト収集で「No files to upload」エラー

## 実施した対策

### ✅ 効果があった対策

1. **完了マーカー方式の導入**
   - `result.sh`で全JSONファイル作成後に`.complete`ファイルを作成
   - `wait_for_nfs.sh`で完了マーカーとJSONファイル両方の存在を確認
   - ファイル: `scripts/result.sh`, `scripts/wait_for_nfs.sh`

2. **ファイル完全性チェック**
   - `result.sh`でJSONファイル作成後に`jq`でバリデーション
   - `sync`コマンドでファイルシステム強制同期
   - ファイル: `scripts/result.sh`

3. **待機時間の大幅延長**
   - 60秒 → 120秒 → 180秒 → **600秒（10分）**に延長
   - **重要**: PBSログ解析により、実際に3分以上の遅延が発生していることが判明
   - ファイル: `scripts/wait_for_nfs.sh`

4. **Jacamar-CI設定の調整**
   - `nfs_timeout`を1分から10分に延長
   - 設定ファイル: Jacamar-CI設定TOML

### ❌ 効果がなかった対策

1. **SSH経由での確認**
   - 計算ノードからログインノードへのSSH接続は不可
   - システム依存の設定が必要で汎用性に欠ける

2. **sudo sync**
   - 権限がないため実行不可
   - 通常の`sync`で十分

3. **group_permissions設定**
   - Jacamar-CIの`group_permissions = true`は権限問題であり、NFS遅延は解決しない

## 現在の設定

### Jacamar-CI推奨設定
```toml
[batch]
command_delay = "30s"
nfs_timeout = "10m"  # 大幅延長：実際に3分以上の遅延が確認されたため
```

### 監視ポイント
- `results`ディレクトリの存在確認
- `.complete`ファイルの存在確認
- JSONファイルの数と完全性
- 待機時間の適切性

## 継続監視が必要な理由
- NFS遅延は環境負荷やネットワーク状況に依存
- 断続的に発生する可能性がある
- システムメンテナンス後に再発する可能性

## 今後の改善案
1. **Jacamar-CI設定の最適化**: `nfs_timeout`をさらに延長
2. **リトライ機能**: ファイル作成失敗時の自動リトライ
3. **詳細ログ**: NFS同期状況のより詳細な記録
4. **アラート機能**: 同期失敗時の通知機能

## 関連ファイル
- `scripts/result.sh`: JSONファイル作成と完全性チェック
- `scripts/wait_for_nfs.sh`: NFS同期待機とファイル確認
- `scripts/matrix_generate.sh`: after_scriptでの同期待機呼び出し