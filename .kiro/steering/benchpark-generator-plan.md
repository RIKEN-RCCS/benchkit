# BenchPark Generator - 将来の実装計画

## 概要

BenchKitの登録アプリケーション設定から、BenchParkの定義ファイルを自動生成するツール（将来的な拡張）。

## 目的

- BenchKitアプリをBenchParkでも実行可能にする
- 手動での定義ファイル作成を自動化
- BenchKitとBenchParkの設定を同期

## 生成対象ファイル

1. **package.py** - Spackパッケージ定義
2. **application.py** - Rambleアプリケーション定義
3. **experiment.py** - Ramble実験定義

## 必要な情報

### BenchKit側（入力）
- `programs/{app}/` - ビルド・実行スクリプト、メタデータ

### BenchPark側（出力）
- アプリケーション名、バージョン
- ビルド依存関係、コンパイラ要件
- 実行コマンド、環境変数
- ワークロード定義、パラメータ

## ファイル構成（将来）

```
benchpark-bridge/
└── generators/
    ├── templates/          # Jinja2テンプレート
    ├── *_generator.py      # 各種ジェネレーター
    └── cli.py              # 統合CLIツール
```

## 優先度

**低優先度** - 結果変換機能の安定化とmainマージ後に着手

## 参考

- BenchPark: https://github.com/LLNL/benchpark
- Ramble: https://github.com/GoogleCloudPlatform/ramble
- Spack: https://spack.readthedocs.io/
