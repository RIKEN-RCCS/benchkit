# システム追加時のトラブルシューティング

新しいシステムをBenchKitに追加する際に遭遇しやすい問題と解決方法をまとめています。

---

## Jacamar-CI関連の問題

### PBSジョブ監視の問題（MiyabiG/MiyabiC事例）

**症状:**
- ベンチマークジョブが実行されない
- GitLab CIログで「NFS同期問題」として現れる
- `wait_for_nfs.sh`が長時間待機後にタイムアウト
- `results`ディレクトリやJSONファイルが作成されない

**根本原因:**
- Jacamar-CIのPBSジョブ状態監視ロジックが、カスタムPBS環境に対応していない
- ジョブがQUEUED状態でも「completed」と誤判定される
- 実際にはジョブが実行されずに次のステップに進んでしまう

**解決方法:**

#### 1. Jacamar-CIの修正が必要な場合

`internal/executors/pbs/tools.go`を以下のように修正：

```go
// completed polls qstat until job is no longer obtainable
func (e *executor) completed() {
    qstat := fmt.Sprintf("%s %s", e.mng.StateCmd(), e.jobID)
    
    fmt.Printf("DEBUG: Starting job monitoring for jobID: %s\n", e.jobID)
    
    // ジョブIDからホスト名部分を除去（比較用）
    jobIDBase := strings.Split(e.jobID, ".")[0]
    fmt.Printf("DEBUG: Base job ID for comparison: %s\n", jobIDBase)
    
    for {
        out, err := e.absExec.Runner.ReturnOutput(qstat)
        fmt.Printf("DEBUG: Running qstat: %s\n", qstat)
        fmt.Printf("DEBUG: qstat output: %s\n", out)
        
        if err != nil {
            fmt.Printf("DEBUG: qstat command failed, checking output content\n")
        }
        
        // ジョブが見つからない場合の判定
        if strings.Contains(out, "No matching job found") || 
           strings.Contains(out, "qstat: Unknown Job Id") {
            fmt.Printf("DEBUG: Job %s not found → completed\n", e.jobID)
            return
        }
        
        // ベースジョブIDで検索（ホスト名なしで比較）
        if strings.Contains(out, jobIDBase) {
            fmt.Printf("DEBUG: Job %s still active\n", e.jobID)
        } else {
            fmt.Printf("DEBUG: Job %s not found → completed\n", e.jobID)
            return
        }
        
        time.Sleep(e.sleepTime)
    }
}
```

#### 2. exitStatus関数の修正

カスタムPBS環境では、JSON形式の`qstat`が使用できない場合があります：

```go
func (e *executor) exitStatus() error {
    // JSON形式ではなく通常形式を使用
    qstat := fmt.Sprintf("%s -H -f %s", e.mng.StateCmd(), e.jobID)
    
    out, err := e.mng.FileOutWrapper(e.absExec.Runner, e.exitCodeFile, qstat)
    if err != nil {
        return fmt.Errorf("failed qstat for exit status: %s", out)
    }
    
    // "No matching job found" の場合は正常終了と見なす
    if strings.Contains(out, "No matching job found") {
        return nil
    }
    
    // Exit_status を抽出
    var exitCode int = 0
    for _, line := range strings.Split(out, "\n") {
        if strings.HasPrefix(strings.TrimSpace(line), "Exit_status") {
            fmt.Sscanf(line, "Exit_status = %d", &exitCode)
            break
        }
    }
    
    if exitCode != 0 {
        return execerr.CustomBuildError(exitCode, 
            fmt.Errorf("job %s failed with exit code %d", e.jobID, exitCode))
    }
    
    return nil
}
```

---

## 診断方法

### 1. Jacamar-CIログの確認

以下のようなログが出力される場合、PBSジョブ監視に問題があります：

```
DEBUG: Starting job monitoring for jobID: 1258470.opbs
DEBUG: Job 1258470.opbs not found in qstat output → completed
```

ジョブが実際にはQUEUED状態なのに「completed」と判定されている場合は修正が必要です。

### 2. PBSジョブの手動確認

```bash
# ジョブの状態を手動で確認
qstat -u $USER

# 特定ジョブの詳細確認
qstat -f <job_id>

# 履歴の確認
qstat -H -f <job_id>
```

### 3. qstat出力形式の確認

システム固有のPBS環境では、qstat出力形式が異なる場合があります：

```bash
# JSON形式が使用可能か確認
qstat -F json <job_id>

# 通常形式の出力確認
qstat -f <job_id>
```

---

## 予防策

### 1. 新システム追加時のチェックリスト

- [ ] PBSのバージョンとカスタマイズ内容を確認
- [ ] `qstat`コマンドの出力形式を確認
- [ ] ジョブIDの形式を確認（ホスト名付きかどうか）
- [ ] Jacamar-CIでテストジョブを実行して動作確認

### 2. テスト方法

```bash
# 簡単なテストジョブでJacamar-CIの動作確認
echo '#!/bin/bash
echo "Test job"
sleep 30
echo "Test completed"' > test_job.sh

# Jacamar-CIでテスト実行
# ログでジョブ監視が正常に動作することを確認
```

---

## 関連ファイル

- `internal/executors/pbs/tools.go`: Jacamar-CIのPBS監視ロジック
- `scripts/wait_for_nfs.sh`: NFS同期待機スクリプト（症状として現れる）
- `.kiro/steering/nfs-troubleshooting.md`: 詳細なトラブルシューティング履歴

---

## 参考情報

- [ADD_APP.md](ADD_APP.md): 新しいアプリケーション追加方法
- Jacamar-CI公式ドキュメント: PBS executor設定
- 各システムのPBSシステム仕様書