# 性能推定支援機能

BenchKit の性能推定支援機能は、ベンチマーク結果の収集・変換・転送を自動化し、外部の性能推定ツールとの接続を支援します。異種ハードウェア間の性能推定にはパフォーマンスカウンタや機密情報が含まれる専用ツール等が必要であり、本機能はそのデータパイプライン部分を担います。

---

## 概要

### データフロー

```
run.sh → results/result → result.sh → Result_JSON
  → send_results.sh（サーバ転送、uuid/timestamp書き戻し）
  → estimate.sh（性能推定）→ Estimate_JSON
  → send_estimate.sh（推定結果転送）
```

### 推定の仕組み

1. ベンチマーク実行（例: MiyabiG で qws を実行）
2. 結果をサーバに送信し、uuid/timestamp を Result_JSON に書き戻し
3. `estimate.sh` が Result_JSON を読み込み、別システム（例: Fugaku）の最新結果を API で取得
4. 両システムの FOM を比較し、性能比（performance_ratio）を算出
5. Estimate_JSON を生成してサーバに送信

### 推定対象システム

`scripts/job_functions.sh` の `ESTIMATE_SYSTEMS` で定義：
```bash
ESTIMATE_SYSTEMS="MiyabiG,RC_GH200"
```

これらのシステムでベンチマーク実行後、自動的に推定パイプラインが起動します。

---

## ファイル構成

```
scripts/
├── estimate_common.sh            # 共通ライブラリ（変数、read_values、fetch_current_fom、print_json）
├── run_estimate.sh               # 推定実行ラッパー（results/result*.json を順に処理）
├── send_estimate.sh              # 推定結果をサーバに転送
├── fetch_result_by_uuid.sh       # UUID指定で結果を取得
└── generate_estimate_from_uuid.sh # UUID指定推定パイプライン YAML 生成

programs/<code>/
└── estimate.sh                   # アプリ固有の推定ロジック
```

---

## estimate_common.sh — 共通ライブラリ

### 提供する関数

| 関数 | 説明 |
|------|------|
| `read_values <json_file>` | Result_JSON を読み込み、グローバル変数に格納 |
| `fetch_current_fom <code> [exp]` | result_server API から Fugaku の最新 FOM を取得 |
| `performance_ratio` | `est_current_fom / est_future_fom` を計算 |
| `print_json` | Estimate_JSON を stdout に出力 |

### read_values が設定する変数

| 変数 | 説明 |
|------|------|
| `est_code` | プログラムコード名 |
| `est_exp` | 実験名（Exp） |
| `est_fom` | FOM 値 |
| `est_system` | 実行システム名 |
| `est_node_count` | ノード数 |
| `est_numproc_node` | ノードあたりプロセス数 |
| `est_timestamp` | サーバ受信タイムスタンプ（`_server_timestamp` または ファイル名から抽出） |
| `est_uuid` | サーバ割当 UUID（`_server_uuid` またはファイル名から抽出） |

### estimate.sh が設定すべき変数

| 変数 | 説明 |
|------|------|
| `est_current_system` | 比較元システム名（例: Fugaku） |
| `est_current_fom` | 比較元 FOM |
| `est_current_target_nodes` | 比較元ターゲットノード数 |
| `est_current_scaling_method` | 比較元スケーリング方法（例: measured） |
| `est_future_system` | 推定先システム名（例: FugakuNEXT） |
| `est_future_fom` | 推定先 FOM |
| `est_future_target_nodes` | 推定先ターゲットノード数 |
| `est_future_scaling_method` | 推定先スケーリング方法（例: scale-mock） |
| `est_current_bench_*` | 比較元ベンチマーク情報（`fetch_current_fom` が自動設定） |
| `est_future_bench_*` | 推定先ベンチマーク情報（estimate.sh が設定） |
| `est_current_fom_breakdown` | 比較元 fom_breakdown JSON 文字列（オプション） |
| `est_future_fom_breakdown` | 推定先 fom_breakdown JSON 文字列（オプション） |

---

## estimate.sh の実装例（qws）

```bash
#!/bin/bash
source scripts/estimate_common.sh

# ベンチマーク結果を読み込み
read_values "$1"

# --- 推定先ベンチマーク情報（実行結果からパススルー）---
est_future_bench_system="$est_system"
est_future_bench_fom="$est_fom"
est_future_bench_nodes="$est_node_count"
est_future_bench_numproc_node="$est_numproc_node"
est_future_bench_timestamp="$est_timestamp"
est_future_bench_uuid="$est_uuid"

# --- 比較元: Fugaku（API から最新結果を取得）---
est_current_system="Fugaku"
fetch_current_fom "$est_code" "CASE0"
est_current_target_nodes="$est_node_count"
est_current_scaling_method="measured"

# --- 推定先: FugakuNEXT（ダミー: FOM を 2 倍）---
est_future_system="FugakuNEXT"
est_future_fom=$(awk -v fom="$est_fom" 'BEGIN {printf "%.3f", fom * 2}')
est_future_target_nodes="$est_node_count"
est_future_scaling_method="scale-mock"

# --- fom_breakdown（区間ごとのスケーリング）---
raw_breakdown=$(jq -c '.fom_breakdown // empty' "$1")
if [[ -n "$raw_breakdown" ]]; then
  est_future_fom_breakdown=$(echo "$raw_breakdown" | jq -c '{
    sections: [.sections[] | {name, bench_time: .time, scaling_method: "scale-mock", time: (.time * 2)}],
    overlaps: [(.overlaps // [])[] | {sections, bench_time: .time, scaling_method: "scale-mock", time: (.time * 2)}]
  }')
  est_current_fom_breakdown=$(echo "$raw_breakdown" | jq -c '{
    sections: [.sections[] | {name, bench_time: .time, scaling_method: "measured", time: .time}],
    overlaps: [(.overlaps // [])[] | {sections, bench_time: .time, scaling_method: "measured", time: .time}]
  }')
  # FOM を breakdown の合算値で再計算
  est_future_fom=$(echo "$est_future_fom_breakdown" | jq '([.sections[].time] | add) - ([(.overlaps // [])[].time] | add // 0)' | awk '{printf "%.3f", $1}')
  est_current_fom=$(echo "$est_current_fom_breakdown" | jq '([.sections[].time] | add) - ([(.overlaps // [])[].time] | add // 0)' | awk '{printf "%.3f", $1}')
fi

# --- 出力 ---
mkdir -p results
print_json > "results/estimate_${est_code}_0.json"
```

---

## Estimate_JSON スキーマ

```json
{
  "code": "qws",
  "exp": "CASE0",
  "current_system": {
    "system": "Fugaku",
    "fom": 0.45,
    "target_nodes": "1",
    "scaling_method": "measured",
    "benchmark": {
      "system": "Fugaku",
      "fom": 0.45,
      "nodes": "1",
      "numproc_node": "2",
      "timestamp": "2026-03-23 10:55:59",
      "uuid": "a1d5c944-..."
    },
    "fom_breakdown": {
      "sections": [
        {"name": "compute_kernel", "bench_time": 0.30, "scaling_method": "measured", "time": 0.30},
        {"name": "communication", "bench_time": 0.20, "scaling_method": "measured", "time": 0.20}
      ],
      "overlaps": [
        {"sections": ["compute_kernel", "communication"], "bench_time": 0.05, "scaling_method": "measured", "time": 0.05}
      ]
    }
  },
  "future_system": {
    "system": "FugakuNEXT",
    "fom": 0.90,
    "target_nodes": "1",
    "scaling_method": "scale-mock",
    "benchmark": {
      "system": "MiyabiG",
      "fom": 5.77,
      "nodes": "1",
      "numproc_node": "1",
      "timestamp": "2026-03-23 11:00:00",
      "uuid": "b2e6d055-..."
    },
    "fom_breakdown": {
      "sections": [
        {"name": "compute_kernel", "bench_time": 0.30, "scaling_method": "scale-mock", "time": 0.60},
        {"name": "communication", "bench_time": 0.20, "scaling_method": "scale-mock", "time": 0.40}
      ],
      "overlaps": [
        {"sections": ["compute_kernel", "communication"], "bench_time": 0.05, "scaling_method": "scale-mock", "time": 0.10}
      ]
    }
  },
  "performance_ratio": 0.500
}
```

### フィールド説明

- `current_system` / `future_system`: 比較する2つのシステム
- `fom`: 推定後の FOM（breakdown がある場合は Σsections.time - Σoverlaps.time）
- `target_nodes`: 推定対象のノード数
- `scaling_method`: スケーリング方法（measured, scale-mock 等）
- `benchmark`: 実ベンチマークの元データ情報
- `fom_breakdown`: FOM の内訳（オプション）
  - `bench_time`: 実ベンチマークでの区間時間
  - `scaling_method`: その区間のスケーリング方法
  - `time`: スケーリング後の推定時間
- `performance_ratio`: `current_fom / future_fom`

---

## UUID 指定による再推定

過去のベンチマーク結果に対して推定を再実行できます。

### API トリガー
```bash
curl -X POST --fail \
  -F token=$TOKEN -F ref=develop \
  -F "variables[estimate_uuid]=a1d5c944-b6ad-4347-a44d-45a3b7760118" \
  -F "variables[code]=qws" \
  https://gitlab.example.com/api/v4/projects/PROJECT_ID/trigger/pipeline
```

### 処理フロー
1. `fetch_result_by_uuid.sh` が UUID で Result_JSON を取得
2. `run_estimate.sh` が `estimate.sh` を実行
3. `send_estimate.sh` が推定結果をサーバに転送

---

## 新しいアプリに推定を追加する

1. `programs/<code>/estimate.sh` を作成（上記の qws 例を参考）
2. `scripts/job_functions.sh` の `ESTIMATE_SYSTEMS` に推定対象システムが含まれていることを確認
3. `programs/<code>/list.csv` に推定対象システムの実行条件を追加
4. CI パイプラインが自動的に推定ジョブを生成

### 必要な環境変数（CI で自動設定）

| 変数 | 説明 |
|------|------|
| `RESULT_SERVER` | 結果サーバの URL |
| `RESULT_SERVER_KEY` | API キー |
