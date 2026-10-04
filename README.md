# meishiDB

セルフホスト名刺管理ソフトウェア。Tailscale など VPN 越しの利用前提。

詳細な設計は [`docs/architecture.md`](docs/architecture.md) を参照。

## 構成サービス

| サービス | 役割 | デフォルトポート |
|---|---|---|
| `web` | Next.js 15 / PWA / shadcn/ui | 3000 |
| `api` | FastAPI / 認証 / CRUD / 監査 | 8000 |
| `ocr` | PaddleOCR（日本語＋英語、CPU） | 8001 |
| `db` | PostgreSQL 16 | 5432 |
| `search` | Meilisearch v1.10 | 7700 |
| `storage` | MinIO（名刺画像） | 9000 / 9001 |
| `scanner-watcher` | フォルダ監視 → 自動投入（任意） | — |
| `proxy` | Caddy（公開ホスト用、任意） | 80 / 443 |

すべてループバックにのみバインド。外部公開する場合は Caddy 経由 (`--profile proxy`) で 80/443 を開ける。

## 機能

- 認証
  - パスワード（Argon2id） ＋ サーバ側セッション (HttpOnly Cookie)
  - **パスキー (WebAuthn / py_webauthn 2.x)** 登録・ログイン
- 名刺
  - 手動 CRUD、タグ、お気に入り、メモ、明示共有 (view/edit)
  - **メモ**: 名刺詳細で追加・編集・削除（最大5000文字）。投稿者・作成日時を表示。共有先も閲覧でき、編集権限の共有先は自分のメモを編集・削除、名刺所有者は全メモを管理できる
  - **画像アップロード**（front/back）→ サムネ自動生成（front, 512px WebP）
  - **OCR**: front 画像アップロード時に同期実行、フィールド自動入力
    - 同じ行の氏名・役職の分割領域を結合し、メールらしい英数字領域は英語モデルで再認識
  - **検索**: Meilisearch（未配線時は Postgres ILIKE フォールバック）
  - **地図** (`/map`): MapLibre GL JS + OSM タイルで住所を地図表示。住所のジオコーディングは自前 Nominatim（任意・`--profile geocoder`）。未設定でも座標を持つ名刺は表示する
  - **エクスポート**: CSV / vCard 3.0
  - **PWA**: manifest + service worker、`/scan` ショートカット
  - **カメラ取り込み**: `<input capture="environment">` でモバイルのリアカメラ起動
- スキャナ連携
  - フォルダに置かれた画像を `scanner-watcher` が監視 → `/api/scanner/import` に POST
- 監査ログ: `audit_logs` に append-only

## 開発環境

### Docker Compose（推奨）

OCRを使うx86_64環境では、CPUにAVX命令セットが必要です。仮想マシンではCPUタイプを
`host`などAVXを公開する設定にしてください。`lscpu`のFlagsで確認できます。
初回のイメージビルドにはディスク容量が必要なため、テスト用VMも40 GB以上を推奨します。

MinIOは公式コンテナイメージが取得できなくなったため、
[`deploy/minio/Dockerfile`](deploy/minio/Dockerfile)で公式ソースの
`RELEASE.2025-10-15T17-29-55Z`をビルドします。初回はGo依存の取得とコンパイルが走ります。
手順の根拠は[MinIO公式リリース](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z)です。

```bash
cp deploy/env.example deploy/.env  # SECRET_KEY などを編集
cd deploy
docker compose up --build
```

| URL | 内容 |
|---|---|
| http://localhost:3000 | Web |
| http://localhost:3000/scan | カメラスキャン |
| http://localhost:3000/map | 名刺の地図表示 |
| http://localhost:3000/settings/passkeys | パスキー管理 |
| http://localhost:8000/docs | FastAPI Swagger |
| http://localhost:8001/healthz | OCR サービス |
| http://localhost:9001 | MinIO 管理コンソール |
| http://localhost:7700 | Meilisearch |

最初に http://localhost:3000/register からアカウント作成。最初のユーザーは admin になる。

> PaddleOCR の初回ビルドは CPU/ネットワーク次第で数分〜10 分以上かかる。`docker compose up ocr` だけ先に走らせておくとよい。

OCRモデルは`ocr_models`ボリュームに保存し、コンテナ更新時にも再利用します。
日本語モデルは起動時、メール再認識用の英語モデルは初回の対象画像処理時に取得します。

### スキャナ連携を使う

1. `deploy/.env` に `SCANNER_API_TOKEN` と `SCANNER_OWNER_EMAIL`（投入先ユーザー）を設定
2. `docker compose --profile scanner up scanner-watcher`
3. ホスト側のフォルダを `scanner_inbox` ボリュームにマウント、または `volumes:` を bind に変更

### 公開ホスト用 Caddy

```bash
PUBLIC_HOST=meishi.example.com docker compose -f docker-compose.yml -f production.yml --profile proxy up -d --build
```

VPN 内ホスト名であれば Caddyfile の該当ホスト指定を `tls internal` 付きに変更。

### ローカル直起動

WebはNode.js 22.12以上を使用してください。DockerはNode.js 22を使用します。

```bash
# API
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload

# Web
cd ../web
npm install
cp .env.example .env.local
npm run dev

# OCR
cd ../ocr
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8001
```

## ディレクトリ

```
meishiDB/
├── api/                # FastAPI
│   ├── app/
│   │   ├── core/       # config, db, security, logging
│   │   ├── models/     # SQLAlchemy
│   │   ├── schemas/    # Pydantic
│   │   ├── routers/    # auth / webauthn / cards / tags / users / search / export / scanner
│   │   └── services/   # audit, ocr_client, storage, search_index
│   └── alembic/
├── ocr/                # PaddleOCR FastAPI worker
│   └── app/            # main / pipeline / extractors
├── scanner-watcher/    # watchdog → /api/scanner/import
├── web/                # Next.js (App Router)
│   ├── app/            # /login /register /cards /scan /tags /settings/passkeys
│   ├── components/     # ui, header, sw-register, card-image-capture
│   ├── lib/            # api クライアント, webauthn ヘルパ, types
│   └── public/         # manifest.webmanifest, sw.js, icon.svg
├── deploy/             # docker-compose, Caddyfile, env.example
└── docs/               # 設計ドキュメント
```

## セキュリティ運用ノート

- `SECRET_KEY` / `MEILI_MASTER_KEY` / `MINIO_ROOT_PASSWORD` は十分に長いランダム文字列に置き換える
- 本番では `production.yml` を重ねる（`!reset`に対応したDocker Composeが必要）。Secure Cookie、API の再読込なし起動、Web の本番ビルドを適用する。`--profile proxy` だけでは開発モードのまま。
- 初回の管理者登録は外部アクセスを制限した状態で済ませてから公開する。公開登録とパスキーの本人確認ポリシーは導入先で決定する。
- WebAuthn は `WEBAUTHN_RP_ID` を本番ドメイン (例: `meishi.example.com`) に、`WEBAUTHN_ORIGIN` を `https://...` に設定
- 更新系APIは`Origin`（なければ`Referer`）を`CORS_ORIGINS`と完全一致で検証する。
  VPNのホスト名やIPアドレスからアクセスする場合も、実際のWeb URL
  （例: `http://meishi.tailnet.example:3000`）を設定する。複数URLはカンマ区切り。
  ブラウザ由来ヘッダーのないCLI・スキャナは引き続き利用できる。
- パスワードログイン、登録、パスキーログインのbegin/finishは、接続元・エンドポイントごとに
  60秒で20回まで。超過時は429と`Retry-After`を返す。制限とパスキーチャレンジは
  単一APIプロセス内で管理する。プロキシの送信元IPを受ける構成では利用者全員で制限を共有する。
  複数ワーカーや利用者ごとの制限が必要な構成では共有ストアと信頼するプロキシの設定が必要。
- 公開 URL に出すなら Caddy + 自動 TLS（`deploy/Caddyfile`）
- 監査ログ（`audit_logs` テーブル）は append-only。MVP では削除エンドポイント無し
- `card.export` は監査ログに必ず記録される（CSV/vCard ともに）

## 未実装 / 将来

- 招待メール（SMTP）→ 現在は open registration、初回ユーザーのみ admin
- 非同期 OCR キュー（ARQ / RQ）。現状は同期呼び出し（front アップロード時に約 5〜30 秒）
- 管理者画面（ユーザー一覧、監査ログ閲覧 UI）
- restic バックアップ運用
- Android ネイティブ（Capacitor）

## 動作確認チェックリスト

- [ ] `docker compose up` で db / api / web / ocr / search / storage が起動する
- [ ] `/register` で初回ユーザーを作成できる
- [ ] `/login` でパスワードログイン → `/cards` にリダイレクト
- [ ] `/settings/passkeys` でパスキーを登録 → ログアウト → `/login` で「パスキーでログイン」
- [ ] `/scan` で写真を撮影 → 自動 OCR → `/cards/{id}` に着地、フィールドが埋まっている
- [ ] `/cards/{id}` で表面/裏面の画像を後から差し替えできる、OCR 再実行ボタンが動く
- [ ] `/cards` で検索（Meili）・タグフィルタ・お気に入りトグルが効く
- [ ] CSV / vCard ボタンからダウンロードできる
- [ ] 共有ダイアログから別ユーザーに view/edit 権限を付与できる
- [ ] スキャナフォルダに画像を置くと `scanner-watcher` が POST して名刺が自動作成される

CSVはExcel等の表計算ソフトでの閲覧向けです。数式の開始文字を含む値には先頭に
アポストロフィを追加します。このCSVを再インポートする場合は値が元データと異なることが
あります。連絡先の移行にはvCardを利用してください。

画像アップロードとOCRは15 MiB、25百万画素、最長辺10,000 pxが上限です。
API・OCRの受信ボディはmultipart分を含め16 MiBまでです。

Meilisearch検索は200件ずつ取得し、ページ送り・CSV/vCardにも同じ結果を使います。
1,000件の上限に到達した場合はPostgreSQLの部分一致検索へ切り替えます。
その場合はOCR全文も検索しますが、Meilisearchのタイプミス補正は適用されません。

2026-10-04の追加レビュー・修正と依存監査は
[`docs/review-followup-2026-10-04.md`](docs/review-followup-2026-10-04.md)を参照してください。
その後の再レビュー、スキャナ/OCRの追加修正、ローカル依存の再監査は
[`docs/review-final-2026-10-04.md`](docs/review-final-2026-10-04.md)を参照してください。
