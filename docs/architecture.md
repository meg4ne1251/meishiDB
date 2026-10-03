# meishiDB 実装プラン（v0）

## Context

`docs/first_plan.md` で定義した「セルフホスト名刺管理ソフト」を、実装可能な単位まで具体化したもの。リポジトリは現状ほぼ空（`docs/first_plan.md` のみ）で、本プランが Phase 0 → MVP のロードマップとなる。

**重視する4本柱**（ユーザー指定）

1. モダンなUI（shadcn/ui + Tailwind、ダークモード中心）
2. OCR性能（PaddleOCR PP-OCRv5 server / CPU）
3. セルフホスト完結（外部API依存ゼロ）
4. セキュリティ（パスキー認証、独自監査ログ）

**ユーザー像**：少人数チーム（〜10名）、デフォルト個人スコープ・明示共有。Proxmox VM 1台に Docker Compose で展開。

---

## 1. アーキテクチャ全体像

```
┌──────────────────────────────────────────────────────────────┐
│  Caddy (Reverse Proxy / Auto-TLS)                            │
└────────────┬──────────────────┬──────────────────────────────┘
             │                  │
   ┌─────────▼────────┐  ┌──────▼────────┐
   │ Web (Next.js)    │  │ API (FastAPI) │
   │ - PWA            │  │ - 認証/CRUD   │
   │ - shadcn/ui      │  │ - 共有/監査   │
   └──────────────────┘  └──┬─────────┬──┘
                            │         │
                ┌───────────▼──┐ ┌────▼──────────┐
                │ OCR Service  │ │ PostgreSQL 16 │
                │ (FastAPI +   │ │ - メタデータ   │
                │  PaddleOCR)  │ │ - 監査ログ     │
                └──────────────┘ └───────────────┘
                            │         │
                ┌───────────▼──┐ ┌────▼──────────┐
                │ MinIO (S3)   │ │ Meilisearch   │
                │ - 名刺画像   │ │ - 全文検索     │
                └──────────────┘ └───────────────┘
                            │
                ┌───────────▼──────────┐
                │ Scanner Watcher       │
                │ (folder → API upload) │
                └───────────────────────┘
```

**サービス一覧**（compose上の単位）

| サービス | 役割 | 技術 |
|---|---|---|
| `web` | フロントエンド／PWA | Next.js 15 (App Router) + TS + Tailwind + shadcn/ui |
| `api` | アプリケーションAPI | FastAPI (Python 3.12) + SQLAlchemy 2.0 + Alembic |
| `ocr` | OCRワーカー | FastAPI + PaddleOCR 3.x (PP-OCRv5 server, CPU) |
| `db` | RDB | PostgreSQL 16 |
| `search` | 検索エンジン | Meilisearch v1.x |
| `storage` | オブジェクトストレージ | MinIO |
| `proxy` | リバースプロキシ／TLS | Caddy 2 |
| `scanner-watcher` | スキャナ連携（任意起動） | Python (watchdog) |

---

## 2. 技術スタック詳細

### Frontend (`web/`)

- **Next.js 15** (App Router, Server Components 主体)
- **TypeScript** strict
- **Tailwind CSS** + **shadcn/ui**（コピー＆所有モデル）
- **lucide-react**（アイコン）
- **TanStack Query**（クライアント側のキャッシュ／OCR進捗ポーリング）
- **react-hook-form** + **zod**（フォーム＋バリデーション）
- **MapLibre GL JS** + OpenStreetMap タイル（住所地図）
- **PWA**: `next-pwa` または手書き service worker。`capture="environment"` で `<input type="file" accept="image/*">` 経由のスマホカメラ起動。
- **デザイン方針**: Linear/Vercel ダッシュボード風。ダークモード基準、余白多め、モーション控えめ。

### Backend API (`api/`)

- **FastAPI**, **uvicorn** (本番は gunicorn + uvicorn workers)
- **SQLAlchemy 2.0** (async) + **Alembic**（マイグレーション）
- **Pydantic v2** スキーマ
- **py_webauthn** (パスキー)
- **passlib[argon2]** (パスワードフォールバック)
- **httpx** (OCRサービスへの内部通信)
- **meilisearch-python-sdk**
- **boto3** または **minio-py** (MinIO アクセス)
- **structlog** (構造化ログ)

### OCR Service (`ocr/`)

- **FastAPI** で `/ocr` エンドポイント1本
- **PaddleOCR 3.x** (PP-OCRv5 server, CPU 推論)
- 画像前処理: OpenCV で傾き補正・リサイズ
- フィールド分類: 正規表現 + 位置ヒューリスティクス
  - 電話番号: `\d{2,4}-\d{2,4}-\d{3,4}` 等
  - メール: 標準 RFC regex
  - 郵便番号: `〒?\d{3}-?\d{4}`
  - 氏名・会社名: 行位置とフォントサイズ（PaddleOCRの bbox 高さ）で推定
- 出力 JSON 例:
  ```json
  {
    "raw_text": "...",
    "fields": {
      "person_name": "山田太郎",
      "person_name_kana": null,
      "company": "株式会社サンプル",
      "title": "営業部長",
      "phone": "03-1234-5678",
      "mobile": "090-...",
      "email": "yamada@example.co.jp",
      "postal_code": "100-0001",
      "address": "東京都千代田区..."
    },
    "confidence": { "person_name": 0.92, ... }
  }
  ```

### データベース

- **PostgreSQL 16**
- **Meilisearch** に検索インデックスを別途持つ（pg_bigm は使わない方針）
- マイグレーションは Alembic で `api/alembic/versions/` 配下に集約

### ストレージ

- **MinIO** に名刺画像（オリジナル + 必要なら正規化版）を保存
- バケット構成:
  - `cards-original/{card_id}/front.jpg`
  - `cards-original/{card_id}/back.jpg`
  - `cards-thumb/{card_id}/front_512.webp`

### リバースプロキシ

- **Caddy 2**: 自動TLS（公開時）、内部VPN運用なら自己署名 or `internal` 発行
- HTTP/2、Brotli 有効化
- セキュリティヘッダ集中設定（CSP, HSTS, X-Frame-Options, Referrer-Policy）

---

## 3. データモデル（初期スキーマ）

```sql
-- 認証
users (
  id UUID PK, email CITEXT UNIQUE, display_name TEXT,
  role TEXT CHECK (role IN ('admin','member')) DEFAULT 'member',
  password_hash TEXT NULL,           -- フォールバック用 Argon2id
  created_at, updated_at, last_login_at
)
webauthn_credentials (
  id UUID PK, user_id FK, credential_id BYTEA UNIQUE,
  public_key BYTEA, sign_count BIGINT, transports TEXT[],
  nickname TEXT, created_at, last_used_at
)
sessions (
  id UUID PK, user_id FK, expires_at, ip INET, user_agent TEXT
)

-- 名刺
cards (
  id UUID PK, owner_id FK users,
  status TEXT CHECK (status IN ('uploaded','ocr_running','ocr_done','confirmed','archived')),
  source TEXT CHECK (source IN ('upload','camera','scanner','manual','email')),
  image_front_key TEXT, image_back_key TEXT,
  scanned_at TIMESTAMPTZ, created_at, updated_at
)
card_fields (
  card_id PK FK cards,
  person_name TEXT, person_name_kana TEXT,
  company TEXT, department TEXT, title TEXT,
  postal_code TEXT, address TEXT,
  phone TEXT, mobile TEXT, fax TEXT,
  email TEXT, website TEXT,
  raw_ocr_text TEXT, ocr_confidence JSONB
)

-- 整理
tags (id UUID PK, owner_id FK, name TEXT, color TEXT, UNIQUE(owner_id, name))
card_tags (card_id FK, tag_id FK, PRIMARY KEY(card_id, tag_id))
card_memos (id UUID PK, card_id FK, author_id FK, body TEXT, created_at)
favorites (user_id FK, card_id FK, PRIMARY KEY(user_id, card_id))

-- 共有（明示共有モデル）
card_shares (
  id UUID PK, card_id FK, shared_by FK users,
  shared_with FK users,                 -- 個人共有
  permission TEXT CHECK (permission IN ('view','edit')),
  created_at
)
-- 将来的に "全社共有" を入れるなら shared_with NULL + scope='org' を導入

-- 監査ログ
audit_logs (
  id BIGSERIAL PK, user_id FK, action TEXT,
  target_type TEXT, target_id TEXT,
  ip INET, user_agent TEXT,
  metadata JSONB, created_at TIMESTAMPTZ DEFAULT now()
)
```

**監査対象アクション**: `login`, `login_failed`, `logout`, `card.view`, `card.create`, `card.update`, `card.delete`, `card.share`, `card.share_revoke`, `card.export`, `card.memo_create`, `card.memo_update`, `card.memo_delete`, `passkey.register`, `passkey.delete`

---

## 4. 主要ユースケース／フロー

### 4.1 名刺登録フロー（撮影〜確定）

1. ユーザーが Web/PWA から画像をアップロード（または scanner-watcher が自動投入）
2. `api` が `cards` レコード作成 → MinIO に画像保存 → status=`uploaded`
3. `api` → `ocr` サービスに同期POST（MVP は同期、10〜30秒で応答）
4. `ocr` が JSON 返却 → `api` が `card_fields` に保存、status=`ocr_done`
5. ユーザーが UI でフィールド確認・修正 → status=`confirmed`
6. `api` が Meilisearch にドキュメント upsert
7. すべての遷移は `audit_logs` に記録

将来的に async（Redis + ARQ もしくは RQ）化を検討。MVP は同期で十分。

### 4.2 検索

- 入力 → デバウンス 200ms → Meilisearch `/indexes/cards/search`
- 表示: 氏名・会社・部署・電話・メール のサムネイル一覧
- フィルタ: タグ、お気に入り、自分のもののみ／共有されたものを含む

### 4.3 共有（明示共有）

- カード詳細画面の「共有」ボタン → ユーザー選択 → permission（view/edit）
- 受け取った側はトップ画面の「共有された名刺」タブで閲覧
- すべて `audit_logs` に記録

### 4.4 エクスポート

- CSV と vCard 3.0
- 範囲: 選択した名刺 / 検索結果全部 / 自分の全名刺
- エクスポート時に `audit_logs` (`card.export`) を必ず記録

### メモ（実装済み）

- 名刺詳細で自由記述メモを追加・編集・削除。投稿者と作成日時を表示し、新しい順に並べる。
- 本文は前後の空白を除去して1〜5000文字。改行は保持する。
- 名刺所有者は全メモを管理、`edit` 共有先は追加と自分のメモの編集・削除、`view` 共有先は閲覧のみ。共有解除後は投稿者でもアクセス不可。
- `card_memos` の既存スキーマを利用。変更の監査ログにはメモIDを記録し、本文を複製しない。

### 4.5 認証フロー

- 初回登録: 管理者が招待リンク発行 → メール認証 → パスキー登録（必須）→ 任意でパスワード設定
- ログイン: パスキー優先、パスワード入力もリンクで提供
- セッション: HttpOnly + Secure + SameSite=Lax の cookie、有効期限14日（パスキー再認証で延長）

---

## 5. セキュリティ方針

| 項目 | 方針 |
|---|---|
| 認証 | パスキー(WebAuthn)主、Argon2idパスワード副 |
| セッション | サーバ側ストア、HttpOnly Cookie |
| CSP | `default-src 'self'`; OSMタイル/MapLibre 必要分を allowlist |
| HSTS | 有効（VPN-only運用なら任意） |
| CSRF | `SameSite=Lax` + state-changing endpoints に CSRF トークン |
| Rate limit | 認証系エンドポイント: 5回/5分/IP（slowapi 等） |
| 監査ログ | 全 sensitive アクションを `audit_logs` に append-only |
| シークレット管理 | `.env` を repo 外、`docker compose` で読み込み |
| バックアップ | （MVP範囲外）restic で MinIO+PostgreSQL を後段実装 |
| 公開境界 | Tailscale/VPN-only 運用を推奨（README に記載） |

---

## 6. リポジトリ構成（提案）

```
meishiDB/
├── docs/
│   ├── first_plan.md        # 既存
│   └── architecture.md      # 本プランの恒久版（後で書き出し）
├── web/                     # Next.js
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── package.json
├── api/                     # FastAPI
│   ├── app/
│   │   ├── routers/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── core/ (config, security, db)
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── ocr/                     # PaddleOCR FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── pipeline.py
│   │   └── extractors.py
│   └── pyproject.toml
├── scanner-watcher/         # 任意起動
│   └── watcher.py
├── deploy/
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── env.example
└── README.md
```

---

## 7. ロードマップ（マイルストーン）

### M0 — 足場づくり（1週間目安）
- リポジトリ初期化、`docker-compose.yml`、Caddyfile
- 各サービスの空 Dockerfile（hello world レベル）
- Alembic 初期マイグレーション、users / sessions テーブル

### M1 — 認証 & 名刺CRUD（最小UI）
- パスワード認証（Argon2id）まずは実装
- パスキー登録／ログイン
- カード作成・一覧・詳細・編集・削除（OCRなしの手動入力）
- 監査ログ記録の枠組み

### M2 — OCR統合
- `ocr` サービス起動、PaddleOCR 動作確認
- アップロード→OCR→フィールド表示→確定
- MinIO 連携、画像サムネ生成

### M3 — 検索・タグ・お気に入り
- Meilisearch 連携
- タグ／お気に入り／メモ
- CSV / vCard エクスポート

### M4 — 共有 & PWA仕上げ
- 明示共有モデル
- PWA manifest、service worker、スマホカメラ取り込み
- ダークモード仕上げ、アクセシビリティ（キーボードナビ）

### M5（将来）
- スキャナ folder watcher
- 非同期OCRキュー
- restic バックアップ
- Android ネイティブアプリ（Capacitor で Web 資産再利用が現実的）

---

## 8. 検証方法

- **OCR**: `tests/fixtures/cards/` に実名刺サンプル（ダミー10枚以上）を置き、`pytest` で抽出フィールドの正答率を計測。CPU での所要時間も記録。
- **API**: `pytest` + `httpx.AsyncClient` で各エンドポイントの正常系／異常系
- **認証**: パスキー登録→ログインのE2Eを Playwright で1本
- **UI**: Playwright で「画像アップロード→OCR完了→確定→検索ヒット」のゴールデンパス
- **手動確認**: `docker compose up` 一発で全サービスが立ち上がり、`https://localhost` で UI が動くこと
- **セキュリティ**: 監査ログが期待通り記録されることを `pytest` で検証

---

## 9. 重要な未決事項（実装着手前に再確認したい）

1. **メール送信**: 招待・パスワードリセット用の SMTP 設定（自前 Postfix or 外部リレー）— セルフホスト原則と矛盾しないか
2. **画像保持期間**: OCR完了後にオリジナル画像を破棄するか永続保持するか（プライバシー観点）
3. **管理者画面の範囲**: ユーザー管理・監査ログ閲覧は管理者ロールのみ。MVP に含めるか
4. **バックアップ運用の優先度**: M2 までに最低限のスナップショット運用を入れるか、M5 まで先送りか

これらは MVP 着手前 / M1 着手前にもう一度すり合わせ予定。

---

## 10. 次のアクション

承認後の最初のコミット候補:

1. `docs/architecture.md` として本プランを project 内に保存
2. `web/`, `api/`, `ocr/` の空雛形を作成
3. `deploy/docker-compose.yml` のスケルトン
4. `README.md` に「Tailscale越し利用前提・MVP進行中」を明記

---

## Critical Files (作成予定)

- `deploy/docker-compose.yml` — 全サービス定義の中核
- `deploy/Caddyfile` — TLS / セキュリティヘッダ
- `api/app/core/security.py` — WebAuthn / Argon2 / セッション
- `api/app/services/ocr_client.py` — OCR サービスへのプロキシ
- `api/app/services/audit.py` — 監査ログ記録
- `ocr/app/pipeline.py` — PaddleOCR 呼び出し
- `ocr/app/extractors.py` — フィールド分類ロジック（要チューニング）
- `web/app/(auth)/login/page.tsx` — パスキーログインUI
- `web/app/cards/[id]/page.tsx` — 名刺詳細・編集（OCR結果確認画面）
