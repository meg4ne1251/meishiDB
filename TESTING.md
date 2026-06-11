# テスト

このリポジトリの4コンポーネントそれぞれにテストを用意しています。

| コンポーネント | フレームワーク | テスト数 | 必要なもの |
|---|---|---|---|
| `api/` (FastAPI) | pytest + pytest-asyncio | 142 | **Docker**（テスト用 `postgres:16` を自動起動） |
| `ocr/` | pytest | 23 (+1 skip) | なし（PaddleOCR は不要・モック） |
| `scanner-watcher/` | pytest | 17 | なし |
| `web/` (Next.js) | Vitest + jsdom | 16 | Node.js |

合計 **198 テスト**。

---

## api/ — バックエンド

モデルが PostgreSQL 専用機能（CITEXT / JSONB / INET / ARRAY / `gen_random_uuid()`、
部分インデックス、`timestamptz`）を多用するため、SQLite ではなく **実 PostgreSQL** に対して
走らせます。`tests/conftest.py` が次を自動でやります:

1. Docker で `postgres:16` を 1 コンテナ起動（コンテナ名 `meishidb_test_pg`、ホストポート `54330`）
2. Alembic マイグレーションを `head` まで適用してスキーマを作成
   （`Base.metadata.create_all` ではなくマイグレーションを使う。モデルとマイグレーションの
   `timestamptz` 定義を一致させるため）
3. engine / `SessionLocal` を `NullPool` 版に差し替え
   （pytest-asyncio の function スコープのイベントループ間で asyncpg コネクションが
   再利用されると落ちるため）
4. 各テスト前に全テーブルを TRUNCATE して分離

### セットアップと実行

```bash
cd api
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # Docker が動いていること
```

- Docker が無い環境では API スイートは自動的に **skip** されます。
- 既に `127.0.0.1:54330` で Postgres が動いている場合（CI で外部 DB を当てる等）は、
  コンテナを起動せずその DB を `meishi_test` データベースとして使います。
  別ポートを使いたいときは `MEISHI_TEST_PG_PORT` を設定してください。

### カバー範囲

`auth`（登録/ログイン/ログアウト/セッション）、`deps`（セッション解決・admin 権限）、
`security`（Argon2 ハッシュ）、`tags`、`cards`（CRUD / 一覧フィルタ / 検索 ILIKE /
お気に入り / アクセス制御）、`cards/geo`、`shares`（権限）、画像アップロード・OCR、
`scanner` 取り込み、`export`（CSV/vCard）、`users` 検索、`webauthn`、監査ログ、
および `geocoder` / `ocr_client` / `search_index` サービス。

MinIO・Meilisearch・OCR サービス・ジオコーダは外部依存なので `monkeypatch` でスタブ化し、
ルーターの分岐を検証します。

---

## ocr/ — OCR ワーカー

正規表現ベースのフィールド抽出（`extract_fields` 等）は純粋ロジックとしてテスト。
`/ocr` エンドポイントは `run_ocr` をスタブ化して抽出＋整形を検証します。
PaddleOCR / paddlepaddle は重いので **インストール不要**（実モデルを使うスモークテストのみ
`paddleocr` 未導入なら skip）。

```bash
cd ocr
# 依存（fastapi, pillow, numpy, opencv-python-headless, pytest, httpx）が入った
# 仮想環境を使う。api/.venv を流用しても可。
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]" pillow numpy opencv-python-headless
.venv/bin/python -m pytest
```

---

## scanner-watcher/ — フォルダ監視

ヘルパ（`_content_type_for` / `_wait_until_stable` / `_move` / `_send` / `Handler`）を
テスト。HTTP 送信は `monkeypatch` でスタブ化します。

```bash
cd scanner-watcher
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]" watchdog httpx
.venv/bin/python -m pytest
```

---

## web/ — フロントエンド

`lib/utils.ts`（`cn`）と `lib/api.ts`（fetch ラッパ・`ApiError`・クエリ文字列生成）を
Vitest でテストします。`fetch` はモック。

```bash
cd web
npm install
npm test          # vitest run
npm run test:watch
```

---

## 補足: テスト作成中に見つかった不具合（修正済み）

1. **モデルの datetime 列が naive だった** — `Session.expires_at` 等の `Mapped[datetime]` が
   `TIMESTAMP WITHOUT TIME ZONE` にマップされ、アプリが渡す tz-aware な値を asyncpg が
   エンコードできず登録/ログインが失敗していた。マイグレーションは `timestamptz` だったので、
   モデル側を `DateTime(timezone=True)` に揃えた（`api/app/models/*.py`）。
2. **`/api/scanner/import` が成功時に 500** — 直前の `db.refresh(card)` で `card.fields`
   が expire され、同期コンテキストの Pydantic シリアライズ中に遅延ロードが走って
   `MissingGreenlet` になっていた。シリアライズ前に `db.refresh(field)` を追加（`scanner.py`）。
