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
- 軽量推定から詳細推定へどう広げるか
- いま何が簡単で、何がまだ重いか

### 推定 package 開発者

新しい推定 package を追加したい場合は、こちらから始めてください。

- [add-estimation-package.md](./add-estimation-package.md)

主に次が分かります。

- package が持つべき責務
- section package と top-level package の分け方
- fallback / not_applicable の返し方
- いま何が共通化できていて、何がまだ重いか

## 先にざっくり知りたいこと

現時点の BenchKit では、次の整理で見ると分かりやすいです。

- 軽量推定の導入はかなり簡単
- 詳細推定は `qws` が参照実装
- app 側は「何を測って何を渡すか」を主に担当
- package 側は「どう推定して、入力不足をどう扱うか」を主に担当
- requested / applied package、applicability、UUID / timestamp、portal 基本表示は共通層でかなり吸収できている

## 仕様を見たい場合

実務ガイドではなく仕様から確認したい場合は、次を参照してください。

- [ESTIMATION_SPEC.md](../cx/ESTIMATION_SPEC.md)
- [ESTIMATION_PACKAGE_SPEC.md](../cx/ESTIMATION_PACKAGE_SPEC.md)
- [ESTIMATE_JSON_SPEC.md](../cx/ESTIMATE_JSON_SPEC.md)
- [REESTIMATION_SPEC.md](../cx/REESTIMATION_SPEC.md)
