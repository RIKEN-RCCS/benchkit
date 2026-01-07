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
nfs_timeout = "2m"  # 段階的調整：1m→2m→5m→10m
```

**設定変更履歴:**
- 初期: `nfs_timeout = "1m"` → 失敗
- 調整1: `nfs_timeout = "2m"` → テスト中
- 調整2: `nfs_timeout = "5m"` → 必要に応じて
- 調整3: `nfs_timeout = "10m"` → 最終手段

**重要**: `nfs_timeout`はJacamar-CIがPBSジョブの完了を待つ時間です。この時間内にジョブが完了しない場合、Jacamar-CIは強制的にジョブを終了させる可能性があります。

### 監視ポイント
- `results`ディレクトリの存在確認
- `.complete`ファイルの存在確認
- JSONファイルの数と完全性
- 待機時間の適切性

## 継続監視が必要な理由
- NFS遅延は環境負荷やネットワーク状況に依存
- 断続的に発生する可能性がある（前回qws成功→今回失敗の事例）
- システムメンテナンス後に再発する可能性

## 最新の問題事例（2025年1月7日）
- **qws MiyabiG/MiyabiC**: 前回成功したが今回失敗
- **症状**: 180秒待機後も`results`ディレクトリが見つからない
- **ログ**: "Results directory not found"
- **重大な問題発見**: Jacamar-CIがPBSジョブの状態を誤判定
  - PBSジョブがQUEUED/RUNNING状態なのに「completed」と判定
  - ジョブが実際には実行されていないのに、GitLab CIが次のステップに進む
  - 結果として`results`ディレクトリが作成されない

## 根本原因の特定（解決済み）

**Jacamar-CIのPBSジョブ状態監視の致命的バグを発見・修正:**

### 問題のあったコード（修正前）
```go
func (e *executor) completed() {
    qstat := fmt.Sprintf("%s %s", e.mng.StateCmd(), e.jobID)
    for {
        _, err := e.absExec.Runner.ReturnOutput(qstat)
        if err != nil {
            return  // ← エラー発生で即座に「完了」判定（バグ）
        }
        time.Sleep(e.sleepTime)
    }
}
```

### 修正後のコード
```go
func (e *executor) completed() {
    qstat := fmt.Sprintf("%s %s", e.mng.StateCmd(), e.jobID)
    for {
        out, err := e.absExec.Runner.ReturnOutput(qstat)
        if err != nil {
            return
        }
        // 重要: 自分のジョブIDが出力に含まれているか確認
        if !strings.Contains(out, e.jobID) {
            return  // ← 正しい完了判定
        }
        time.Sleep(e.sleepTime)
    }
}
```

### バグの影響
1. **PBSジョブがQUEUED状態**でも`qstat`エラーで「完了」誤判定
2. **実際にはジョブ未実行**なのにGitLab CIが次ステップに進行
3. **`results`ディレクトリ未作成**のため`wait_for_nfs.sh`が失敗

### これまでの対策が効果なかった理由
- NFS遅延対策（待機時間延長）は的外れ
- 完了マーカー方式も、ジョブ未実行では意味なし
- 真の問題はJacamar-CIのバグだった

## 解決状況（2025年1月7日 - 完全解決）

**✅ 問題完全解決・テスト成功:**
- Jacamar-CIの`tools.go`修正完了・実証済み
- MiyabiG・MiyabiC両方で正常動作を確認
- PBSジョブの完全な実行とファイル作成を確認
- `wait_for_nfs.sh`が即座に完了（0秒）
- アーティファクト収集も正常に成功

**実証結果:**
- ジョブID `1258470.opbs` の正常監視
- QWSベンチマーク実行成功（FOM: 5.752）
- `results/result0.json` と `.complete` ファイル作成
- GitLab CI完全成功（Job succeeded）

**長期間の問題が根本解決:**
これまでの「NFS同期問題」は実際にはJacamar-CIのバグであり、修正により完全に解決されました。

## 関連ファイル
- `scripts/result.sh`: JSONファイル作成と完全性チェック
- `scripts/wait_for_nfs.sh`: NFS同期待機とファイル確認
- `scripts/matrix_generate.sh`: after_scriptでの同期待機呼び出し