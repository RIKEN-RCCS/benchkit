# 性能推定の導入ガイド

このドキュメントは、BenchKit の性能推定まわりの入口ページです。
実際の作業は「アプリ側の導入」と「推定 package 側の追加」に分かれるので、まずは自分の立場に近いガイドから見てください。

## 推定まわりの現時点の責務分担

推定まわりはまだ整理中の部分がありますが、現時点では次の分担で考えると実装しやすいです。
配置場所や細かな API は今後変わる可能性があります。package 固有の処理と BenchKit 共通処理を分けておくと、後で配置が変わっても追従しやすくなります。

| 担当 | 主に決めること | 主に触る場所 |
|---|---|---|
| app 担当 | FOM、section / overlap 名、各 item に使う推定 package、app 固有の採取・実行方法 | `programs/<code>/run.sh`, `programs/<code>/estimate.sh`, `programs/<code>/list.csv` |
| 推定担当 | 推定ロジック、必要入力、不足時の fallback / not_applicable、model metadata、assumptions / measurement / confidence / notes | `scripts/estimation/packages/`, `scripts/estimation/section_packages/` |
| 拠点担当 | system / queue / runner / scheduler の登録、拠点表示情報、接続確認、ジョブ投入条件 | `config/system.csv`, `config/queue.csv`, `config/system_info.csv`, [add-site.md](./add-site.md) |
| BenchKit 共通層 | current / future flow、Estimate JSON 組み立て、requested / applied package 記録、portal 表示、共通 helper | `scripts/estimation/common.sh`, `scripts/result.sh`, `scripts/result_server/`, `result_server/` |
| admin / reviewer / approver | 現時点では同じ運用ロールとして、推定関連の変更内容の確認、手動 CI、PR 取込判断を行う | GitHub PR、GitLab manual CI、portal admin |

scaffold や自動生成は、あると便利な支援機能ですが必須ではありません。
既存例とこのガイドを見ながら追加できる状態をまず正とし、必要になった時点で補助ツールを検討します。

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
