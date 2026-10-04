# 2026-10-04 追加レビュー

API、Web、OCR、scanner-watcher、配布設定を確認し、既存テストの実行に加えて
不正入力・画像差し替え中のOCR・ファイル種別を再現テストで検証した。
既存の2026-10-03・2026-10-04の修正を前提に、次の問題を追加修正した。

## 発見事項と修正

| 優先度 | 問題・発生条件 | 修正 |
|---|---|---|
| 高 | スキャナの監視フォルダに画像名のシンボリックリンクを置くと、リンク先の読めるファイルをAPIへ送信する。送信直前にFIFOへ置き換えられた場合にはファイルを開く処理が停止し得る。 | lstatによる通常ファイルの検証、利用可能な環境でのO_NOFOLLOW/O_NONBLOCK、開いたファイルのデバイス・inodeの再照合を追加。検証完了前に内容を送信しない。 |
| 高 | 依存監査でWebの23パッケージ、既存Python環境の14パッケージ・78件の既知脆弱性報告を検出。これは報告の件数であり、本アプリへの侵入成功件数ではない。 | MapLibre/Vitest/PostCSSと推移依存を更新し、Next.js内のPostCSS・sharpにも修正版を指定。Pythonの影響する依存に修正版の最低バージョンを設定。Web本番イメージから開発用依存を削除。 |
| 中 | 古い画像のOCR処理中に表面画像を差し替えると、遅れて完了した古いOCRが氏名以外の空欄・OCR全文・処理状態を新しい画像へ書き込む。古いOCR失敗でも新しい処理状態を戻していた。 | 保存キーをアップロードごとに分け、OCRが参照したキーと現在のキーをロック内で照合する。失敗時の更新も画像キーとocr_running状態を条件にする。 |
| 中 | OCR失敗時に、処理中の手動操作でconfirmedになった名刺をuploadedへ戻す。アップロード開始時にもconfirmed/archivedを戻していた。 | 確認済み・アーカイブ状態を維持。新しいOCR情報は引き続き空欄だけを補完し、手入力を保護する。 |
| 中 | NULを含む氏名・メモ・タグ・検索語などがDB例外になる。不正なUnicodeは422のエラー応答自体のエンコードでも500になる。 | PostgreSQLに渡す文字列を検証し422を返す。パスワードも有効なUnicodeを検証し、検証エラーから入力値を除外して秘密情報やエンコードできない値を反射しない。 |
| 中 | 1×10,000pxなど、許容範囲内の細長い画像をOCR向けに縮小すると片辺が0pxになり処理に失敗する。 | 縮小後の各辺を最低1pxにする。縦横の回帰テストを追加。 |
| 低 | 共有先検索の「%%」「__」などがSQL LIKEのワイルドカードとして解釈され、入力した文字と異なるユーザーを返す。 | 名刺検索と同様にワイルドカードをエスケープする。SQLインジェクションが成立したという意味ではない。 |

画像は同じアップロード内で原本とサムネイルのキーを対応させるため、サムネイル生成が
失敗した際にも以前の画像のサムネイルを表示しない。既存の画像キーは引き続き読める。
スキャナ用トークンの比較も定数時間比較へ変更した。

DBにNULを保存できないことは[PostgreSQL公式仕様](https://www.postgresql.org/docs/16/datatype-character.html)に照合した。
依存更新の根拠には[MapLibre公式アドバイザリ](https://github.com/maplibre/maplibre-gl-js/security/advisories/GHSA-jrc7-96c5-q579)、
[Vitest公式アドバイザリ](https://github.com/vitest-dev/vitest/security/advisories/GHSA-5xrq-8626-4rwp)、
[sharp公式アドバイザリ](https://github.com/lovell/sharp/security/advisories/GHSA-rgj7-g3m4-5g8c)と監査結果を使用した。
現在の地図は固定のattributionとエスケープ済みの名刺項目を使用しているため、
MapLibreの報告をそのまま本アプリでのXSS成立とみなしてはいない。

## 検証結果

| 検証 | 結果 |
|---|---|
| API・実PostgreSQL・Alembic | 223件成功（全体222件＋後から追加したエラー応答のテスト1件） |
| OCR | 72件成功、実モデルのテスト1件skip |
| scanner-watcher | 21件成功 |
| Web | 39件成功 |
| 合計 | 355件成功、1件skip |
| Web型チェック・lint・本番ビルド | 成功 |
| Node.js 22のWeb本番Dockerビルド・起動 | 成功。ログイン画面・静的ファイルのHTTP 200、開発用依存の除外を確認 |
| Web本番用依存のnpm audit | 報告0件 |
| 新規構築したPython検証環境のpip-audit・pip check | 報告0件・依存整合性成功 |
| OCR本体の依存解決とPyPI脆弱性情報の確認 | Python 3.12で63パッケージを確認。PaddlePaddle 2.6.2に2件の報告が残る |
| Python変更箇所の基本Ruff検査・git diff --check | 成功 |

APIの初期テストは211件成功。最初に追加した9件は修正前にすべて失敗し、修正後に成功した。
スキャナのシンボリックリンク送信と、不正Unicodeのエラー応答も修正前に再現した。
検証中に見つかったメモ本文の空白除去と長さ判定の順序も修正し、既存テストで再確認した。

検証ログは`/tmp/meishidb-review-api-final.log`、
`/tmp/meishidb-review-password-validation.log`、
`/tmp/meishidb-review-followup-ocr.log`、`/tmp/meishidb-review-web-tests.log`等。
一時ファイルは後から削除される可能性がある。依存監査の集計と検証環境のバージョンは
[`security-audit-followup-2026-10-04.json`](security-audit-followup-2026-10-04.json)に保存した。

## 適用条件と残る制約

WebはNode.js 22.12以上が必要。DockerのベースもNode.js 22へ変更した。
MapLibreの名前付きエクスポートと、更新後のVitest/ViteのJSX設定へ対応している。
Pythonも依存の再インストール、Docker利用時は各サービスの再ビルドが必要。
DBマイグレーションは不要。

開発用依存の監査にはbracesを起点とする7パッケージのhigh報告が残る。
検証時点のbraces最新版3.0.3も影響範囲に含まれるため、バージョン更新だけでは解消しない。
これらはTailwindのビルド・ESLint系の依存で、本番イメージから除外した。
未信頼のソースやglobパターンを開発・ビルド環境に持ち込む場合は追加対策が必要。
Python依存には完全なロックを追加していないため、将来の再解決でも同じ環境になる保証はない。

OCRはPaddleOCR/PaddlePaddleの2系APIを使用している。PyPIのバージョン情報に基づく追加監査で、
解決されたPaddlePaddle 2.6.2にCVE-2024-0817（IrGraph.draw）と
CVE-2024-0815（_wget_download）のコマンドインジェクション報告が残った。
[描画処理の上流修正](https://github.com/PaddlePaddle/Paddle/commit/bdf6234fdc22e6ee7948950d271cbbe1d27edc93)と
[wget処理の上流修正](https://github.com/PaddlePaddle/Paddle/commit/4c0888d7b8f10405e2e79adc41c224264f93e816)も確認した。
本アプリはユーザーからグラフ描画のパス・モデル取得URLを受け付けていないため、
名刺画像からこの脆弱性を利用できる経路は今回確認していない。
報告対象の関数まで含めたライブラリの解消には3系への移行と実モデルでの互換性検証が必要で、
今回未実施。Python検証環境の報告0件と、このOCR基盤の残課題を混同しないこと。
OCRの追加監査はPython 3.12での依存解決であり、DockerのPython 3.10実環境の監査ではない。

新しい画像はアップロードごとに保存する。差し替え前のオブジェクトは名刺削除時に
まとめて削除されるため、差し替え回数に応じてストレージ使用量が増える。
通常のフィールド編集同士や検索インデックス更新の順序には、厳密なバージョン競合検出はない。

実PaddleOCRモデルの推論、実機のパスキー・カメラ・WebGL地図、MinIO/Meilisearch/Nominatimの
結合、全Composeサービスの起動、侵入・負荷試験は未実施。
Python監査の報告0件はAPI・スキャナ・OCRの軽量テスト用環境についての結果であり、
PaddleOCR本体の依存、OSパッケージ、既存の稼働環境まで含む保証ではない。
公開登録・最初の登録者が管理者になる仕様、単一プロセスの認証制限などの適用条件は
既存READMEと前回レビューの運用ノートに従う。
