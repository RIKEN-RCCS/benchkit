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

## 境界面として固定するもの

責務分担を保つため、層をまたいで渡してよいものは境界面として定義された artifact / metadata に限定します。
個別アプリや個別 package の環境変数を、BenchKit 共通層や別 package が知っている前提にしてはいけません。

### app wrapper が共通層へ渡すもの

`programs/<code>/run.sh` と `programs/<code>/estimate.sh` は、アプリ固有の採取方法や補正を内部で吸収し、共通層へは次の形で渡します。

- `results/result` の `FOM:` / `SECTION:` 行
- `SECTION:` 行の `name`, `time`, `type`, `members`, `estimation_package`, `artifact`, `candidate_estimation_packages`
- `padata*.tgz` などの profiler archive
- `results/estimation_artifacts/` 配下の軽量な推定補助 artifact
- `result*.json` / `estimate*.json` に入る共通 metadata

app 固有の kernel 名、入力短縮、launch window、module、compiler、site 差分は `programs/<code>/` 以下に閉じます。
それらを共通層へ伝える必要がある場合は、app 側で共通 metadata や artifact path に変換してから渡します。

### profiler helper が保証するもの

`bk_profiler` は、指定された profiler を実行し、出力を共通 archive 形式に包むことだけを担当します。
どの kernel を採取するか、何回実行するか、入力を短くするか、どの section に対応するかは app wrapper の責務です。

`bk_profiler` が保証する境界面は次です。

- archive path
- `bk_profiler_artifact/meta.json`
- raw / report の共通配置
- `tool`, `level`, `reports[].kind`, profiler option summary などの機械判定用 metadata

### 推定 package が要求するもの

推定 package は、自分が必要とする入力と書式を package metadata と applicability で定義します。
入力が足りない場合は、package 側が `fallback` / `not_applicable` / `missing_inputs` を返します。

推定 package が参照してよいものは、原則として次です。

- package 自身の環境変数
- `item_json` に入った section / overlap metadata
- `artifact` で渡された共通 artifact
- package 自身が定義する input CSV / prediction CSV / profiler archive 書式
- package 自身の external tool checkout / runtime

推定 package は、`programs/<code>/` 固有の環境変数や app 名を直接見て分岐しないでください。
app 固有の対応付けが必要な場合は、app wrapper が `SECTION:` metadata、artifact path、kernel selector などの package が理解できる入力に変換します。

### BenchKit 共通層が担当するもの

BenchKit 共通層は、app や package の内部意味を解釈せず、宣言された共通 metadata を使って処理します。

- current / future flow
- package dispatch
- requested / applied package の記録
- fallback / applicability の保持
- Estimate JSON 生成
- result / estimate / artifact upload
- portal 表示に必要な共通 metadata の整形

共通層に app 固有・package 固有の例外分岐を入れたくなった場合は、まず app wrapper または package metadata で表現できないかを検討してください。

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
