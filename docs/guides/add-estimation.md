# 性能推定の導入ガイド

このドキュメントは、BenchKit の性能推定まわりの入口ページです。
実際の作業は「アプリ側の導入」と「推定 package 側の追加」に分かれるので、まずは自分の立場に近いガイドから見てください。

## どこから読むか

### アプリ開発者

既存アプリに推定を載せたい場合は、こちらから始めてください。

- [add-estimation-to-app.md](./add-estimation-to-app.md)

主に次が分かります。

- `run.sh` で何を出せばよいか
- `estimate.sh` をどこまで薄くできるか
- `weakscaling` から詳細推定へどう広げるか
- 今後の改善

### 推定 package 開発者

新しい推定 package を追加したい場合は、こちらから始めてください。

- [add-estimation-package.md](./add-estimation-package.md)

主に次が分かります。

- パッケージが持つべき責務
- 区間パッケージと上位パッケージの分け方
- 代替 / not_applicable の返し方
- 今後の改善

## 先にざっくり知りたいこと

現時点の BenchKit では、次の整理で見ると分かりやすいです。

- 最小の導入経路は `weakscaling`
- 詳細推定は `qws` が参照実装
- app 側は「何を測って何を渡すか」を主に担当
- package 側は「どう推定して、入力不足をどう扱うか」を主に担当
- model 名、model type、measurement / confidence / notes / assumptions の既定値は package metadata 側へ寄せる方向で整理が進んでいる
- BenchKit 共通層は current / future の flow、Estimate JSON の組み立て、requested/applied package や applicability の保持を主に担当する
- 要求パッケージ / 実適用パッケージ、applicability、UUID / timestamp、portal の list/detail 表示に必要な基本情報は共通層でかなり吸収できている

## 仕様を見たい場合

実務ガイドではなく仕様から確認したい場合は、次を参照してください。

- [ESTIMATION_SPEC.md](../cx/ESTIMATION_SPEC.md)
- [ESTIMATION_PACKAGE_SPEC.md](../cx/ESTIMATION_PACKAGE_SPEC.md)
- [ESTIMATE_JSON_SPEC.md](../cx/ESTIMATE_JSON_SPEC.md)
- [REESTIMATION_SPEC.md](../cx/REESTIMATION_SPEC.md)
