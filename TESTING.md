# テスト

このリポジトリの4コンポーネントそれぞれにテストを用意しています。

| コンポーネント | フレームワーク | テスト数 | 必要なもの |
|---|---|---|---|
| `api/` (FastAPI) | pytest + pytest-asyncio | 235 | **Docker**（テスト用 `postgres:16` を自動起動） |
| `ocr/` | pytest | 86 (+1 skip) | なし（PaddleOCR は不要・モック） |
| `scanner-watcher/` | pytest | 21 | なし |
| `web/` (Next.js) | Vitest + jsdom | 39 | Node.js |

合計 **381 テスト**（別途 OCR 実モデルのテスト1件は依存未導入時に skip）。

2026-10-04の実環境再検証では、最終OCRイメージの実モデル込み87件も成功。
HTTPS結合・ブラウザ・スキャナ・依存監査の結果は
[`docs/runtime-validation-2026-10-04.md`](docs/runtime-validation-2026-10-04.md)を参照。

実HTTPSのセキュリティチェックは専用テストアカウントで実行します。
合成名刺を1件作成・削除するため、運用利用者のアカウントは使わないでください。
アカウントJSONは`admin_email`と`password`を含む既存の非公開ファイルを指定します。

```bash
python deploy/checks/security_runtime.py \
  --accounts deploy/test-accounts.json --ca deploy/test-root-ca.crt \
  --output /tmp/security-results.json
```

`--check-rate-limit`を付けると同じ接続元のパスキーログイン完了APIに
21回の不正要求を送り、429を確認します。直後のパスキー試験と併走しないでください。
実OCRサービスの比較は[`ocr/evaluation/README.md`](ocr/evaluation/README.md)を参照。

---

## api/ — バックエンド

モデルが PostgreSQL 専用機能（CITEXT / JSONB / INET / ARRAY / `gen_random_uuid()`、
部分インデックス、`timestamptz`）を多用するため、SQLite ではなく **実 PostgreSQL** に対して
走らせます。`tests/conftest.py` が次を自動でやります:

1. Docker で `postgres:16` を 1 コンテナ起動（コンテナ名 `meishidb_test_pg_<port>`、ホストポート `54330`）
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
  Dockerへのアクセスなしで、その Postgres の `meishi_test` データベースを使います。
  別ポートを使いたいときは `MEISHI_TEST_PG_PORT` を設定してください。

### カバー範囲

`auth`（登録/ログイン/ログアウト/セッション）、`deps`（セッション解決・admin 権限）、
`security`（Argon2 ハッシュ）、`tags`、`cards`（CRUD / 一覧フィルタ / 検索 ILIKE /
お気に入り / アクセス制御）、`cards/geo`、`shares`（権限）、`memos`（CRUD / 本文検証 / 共有・投稿者権限 / 共有解除 / 監査）、画像アップロード・OCR、
`scanner` 取り込み、`export`（CSV/vCard）、`users` 検索、`webauthn`、監査ログ、
および `geocoder` / `ocr_client` / `search_index` サービス。

`test_review_20261004.py`では送信元検証、認証制限、不正パスキー入力、
同時登録・共有・お気に入り、OCR中の手動編集、200件を超える検索、
画像欠落、vCard改行、タグ色の消去、共有先の編集権限も検証します。

`test_review_followup.py`では画像差し替え中の古いOCR結果・失敗通知の除外、
確認済み状態の保護、不正な文字の422応答、エラー応答でのパスワード非表示、
ユーザー検索のワイルドカードを検証します。

追加レビューでは、スキャナOCR中の確認・画像差し替え・削除、OCR応答の不正な文字列・型・信頼度、
エラーログへ名刺情報を含めないことも検証します。

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
テスト。シンボリックリンクとFIFOが送信されないことも検証します。
HTTP 送信は `monkeypatch` でスタブ化します。

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
`components/card-memos` は React DOM で表示・追加失敗時の入力保持・再試行・編集・削除確認・閲覧権限・本文の安全な表示も検証します。
`app/review-fixes.test.tsx`では認証キャッシュ分離、OCR後のフォーム更新、編集中の項目とタグの保護、変更項目だけの送信、一覧のページ送り、トップのリダイレクトを検証します。
共有画像の閲覧・view/editのフォーム制御・保存失敗時の入力保持・画像差し替え・スキャン再試行も検証します。
`tests/sw.test.ts`はService Workerの実ファイルをVMで実行し、認証データの除外、静的ファイルのキャッシュ、旧キャッシュの削除を検証します。

```bash
cd web  # Node.js 22.12以上
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
