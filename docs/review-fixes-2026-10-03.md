# 2026-10-03 レビュー対応

[レビュー原文](review-2026-10-03.md)の番号に対応した修正記録です。

| 項目 | 対応 |
|---|---|
| 1. アカウント共通キャッシュ | ユーザーIDを境界にQueryClientを作り直し、旧クエリをキャンセル・破棄。認証完了後はページを再読み込みしてNext.jsのページキャッシュも更新。ログアウト失敗は画面に表示する。 |
| 2. Service Worker | キャッシュを公開静的ファイルに限定。RSC、ページ、API、private/no-store/no-cache応答を除外。v1キャッシュを削除する。オフライン表示はユーザー情報を含まない固定HTML。 |
| 3. OCR後のフォーム保存 | OCR返却値をキャッシュ・フォームへ反映。再取得時は編集中のフィールドとタグを保持し、PATCHは変更したフィールド・タグだけを送る。保存と画像処理の同時操作を抑止する。 |
| 4. 本番起動 | `deploy/production.yml`を追加。production、Secure Cookie、再読込なしAPI、Web本番ビルドを指定し、開発用マウントを外す。公開ホスト名とSECRET_KEYは必須。本番CookieのSecure属性をテストした。 |
| 5. CSV数式 | 数式開始文字・先頭のタブ/改行等を含む値にアポストロフィを付ける。CSVは表計算向けで再インポート時に値が変わることをREADMEへ記載する。 |
| 6. 画像制限 | 通常アップロード、スキャナ、OCRを15 MiBへ統一し、読み込み中にも判定。API/OCRの受信ボディは16 MiB。画像は25百万画素・最長辺10,000 pxまで。Caddyにもボディ制限を設定する。 |
| 7. 同期処理 | MinIO、画像検証、Pillow、Argon2、OCR推論をスレッドへ退避。MinIOに接続・読み取りタイムアウトと再試行上限を設定。APIのOCR同時呼び出しは共通で5件、OCRモデルの利用は1件、待機は5秒まで。本番API/OCRの接続処理にも同時実行上限を設定する。 |
| 8. 共有検索 | 通常更新をMeilisearchの部分更新に変更し、shared_withを含めない。全件再インデックスではDBの共有先を引き続き設定する。 |
| 9. 更新日時 | 名刺フィールド・タグ・画像・OCR・手動座標更新でupdated_atを明示更新。名刺一覧の同時刻の順序はIDで安定させる。 |
| 10. エクスポート検索 | 一覧とエクスポートのテキスト検索を共通化し、電話・携帯・住所・かな・部署・役職も同じ条件で検索する。 |
| 11. トップページ | 認証確認のみをtry/catchで囲み、redirectは外へ移す。 |
| 12. source検証 | DBと同じ5種類のLiteralに限定し、不正値は422にする。 |
| 13. ページ送り | 50件ごとの前後ページを追加。検索・スコープ・お気に入り・タグの変更で先頭へ戻る。 |
| 14. OCR住所の座標 | 通常アップロード、OCR再実行、スキャナの共通OCR適用処理で、新しい住所のジオコーディングを予約。住所一致を条件としたDB更新で、処理中に変更された住所へ古い座標を書き込まない。手動取得で競合した場合は409。 |
| 15. スキャナ同名ファイル | 移動先を排他的に予約し、同名の場合はUUIDを付けて既存ファイルを保護する。 |
| 16. スキャナ移動失敗 | ファイル単位で例外を捕捉し、移動だけを3回まで試行。失敗はログへ記録し次のファイルへ進む。停止したworkerの監視・再起動も追加する。 |

## 依存・ビルド

Next.jsとeslint-config-nextを15.5.27に更新し、package-lock.jsonを更新した。
根拠は[Next.js公式の2026年9月セキュリティ更新](https://nextjs.org/blog/september-2026-security-release)。
WebのDockerビルドはロックファイルをコピーしてnpm ciを実行する。
各コンポーネントのDockerビルドからローカル依存、キャッシュ、環境ファイルを除外した。
テスト用DBコンテナ名はポート番号で分離し、別ポートの検証との衝突を防ぐ。

## 検証

- API: 182件成功（既存155件と追加の回帰テスト27件）。実PostgreSQLとAlembicを使用。
- OCR: 26件成功、実モデルの1件skip。
- scanner-watcher: 19件成功。
- Web: 34件成功。実QueryClient、react-hook-form、React DOMで画面を検証し、Service Workerは実ファイルをVM内で実行。
- Web型チェック、本番ビルド、Python変更箇所のRuff、Service Worker構文、production Composeの構文とマージ結果も成功。

## 適用と検証範囲

本番では`deploy/`で次を実行する。`!reset`に対応したDocker Composeが必要（5.6.0で検証）。
[Compose公式のマージ仕様](https://docs.docker.com/reference/compose-file/merge/#reset-value)に従って開発マウントを削除する。

```bash
docker compose -f docker-compose.yml -f production.yml --profile proxy up -d --build
```

`deploy/.env`のSECRET_KEYとPUBLIC_HOSTを設定する。`--profile proxy`だけの起動は開発設定のまま。
新しいService Workerが有効になると古いmeishiDBキャッシュを削除する。

初回管理者の登録と公開登録の制限、ログイン・登録の試行回数制限、パスキーの本人確認必須化は、
導入先の利用者・プロキシ・認証方針に合わせた追加設計が必要。初回登録を完了するまでは外部アクセスを制限する。
Python依存のロックは今回追加していない。特にPaddleOCRの対応Python・CPU環境を含めて固定とビルド検証が必要。

実PaddleOCR推論、MinIO/Meilisearch/Nominatimとの結合、全サービスのDocker起動、
実ブラウザE2E・負荷試験は未実施。外部サービスはスタブ化した回帰テストで挙動を確認した。
同じフィールドを複数ユーザーが同時編集する場合の厳密な競合検知は追加していない。
スキャナ移動が3回とも失敗したファイルは元の場所に残るため、ログ確認と退避が必要。
