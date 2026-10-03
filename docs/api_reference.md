# meishiDB API リファレンス（webGUI 作り直し用）

> 既存バックエンド（FastAPI, `api/`）が提供する全エンドポイントと、画面に表示できるデータ構造、
> 現在のフロントエンド（`web/`）のページ構成をまとめたもの。webGUI を作り直す際の基礎資料。
>
> 最終確認: 2026-06-15 時点のコード（`api/app/routers/*`, `api/app/schemas/*`, `api/app/models/*`）。

---

## 1. API エンドポイント全一覧

- すべて `/api` プレフィックス付き（`main.py` で各ルーターに `prefix="/api"`）。
- 特記なき限り **セッション Cookie 認証が必須**（`get_current_user` 依存）。
- Cookie は HttpOnly + SameSite=Lax。`auth/login`・`auth/register`・`webauthn/login/finish` で発行。

### 🔐 認証 `/api/auth`

| Method | Path | Body | 返り値 | 備考 |
|---|---|---|---|---|
| POST | `/auth/register` | `{email, display_name, password(8字以上)}` | `CurrentUser` | 201・初回ユーザーは `admin`、以降 `member`・Cookie 発行 |
| POST | `/auth/login` | `{email, password}` | `CurrentUser` | Cookie 発行 |
| POST | `/auth/logout` | — | `{ok: true}` | Cookie 削除 |
| GET | `/auth/me` | — | `CurrentUser` | 未ログインは 401 |

### 🔑 パスキー (WebAuthn) `/api/webauthn`

| Method | Path | Body | 返り値 |
|---|---|---|---|
| POST | `/webauthn/register/begin` | — | `{challenge_id, options}` |
| POST | `/webauthn/register/finish` | `{challenge_id, credential, nickname?}` | `{id, nickname}` |
| GET | `/webauthn/credentials` | — | `[{id, nickname, created_at, last_used_at}]` |
| DELETE | `/webauthn/credentials/{id}` | — | 204 |
| POST | `/webauthn/login/begin` | `{email?}` | `{challenge_id, options}` |
| POST | `/webauthn/login/finish` | `{challenge_id, credential}` | `CurrentUser` |

> チャレンジは API プロセス内のオンメモリキャッシュ（TTL 5分）。複数ワーカー化時は Redis 等へ要置換。

### 📇 名刺 `/api/cards`（中核）

| Method | Path | パラメータ / Body | 返り値 |
|---|---|---|---|
| GET | `/cards` | query: `scope`(owned/shared/all)・`q`・`favorite`・`tag_id`・`limit`(1〜200, 既定50)・`offset` | `CardListResponse {items[], total}` |
| POST | `/cards` | `{source, fields, tag_ids[]}` | `CardDetail`（201） |
| GET | `/cards/geo` | query: `scope` | `CardGeoResponse {items[]}`（座標を持つ名刺のみ・最大 5000） |
| GET | `/cards/{id}` | — | `CardDetail` |
| PATCH | `/cards/{id}` | `{status?, fields?, tag_ids?}` | `CardDetail` |
| DELETE | `/cards/{id}` | — | 204（owner のみ） |
| POST | `/cards/{id}/image` | multipart: `image`・`side`(front/back)・`run_ocr`(bool) | `CardDetail`（front + run_ocr で OCR 実行） |
| GET | `/cards/{id}/image` | query: `side`(front/back)・`thumb`(bool) | 画像バイナリ |
| POST | `/cards/{id}/ocr` | — | `CardDetail`（front 画像で OCR 再実行） |
| POST | `/cards/{id}/geocode` | — | `CardDetail`（住所 → 座標） |
| POST | `/cards/{id}/favorite` | — | 204 |
| DELETE | `/cards/{id}/favorite` | — | 204 |
| GET | `/cards/{id}/shares` | — | `ShareInfo[]`（owner のみ） |
| POST | `/cards/{id}/shares` | `{user_email, permission(view/edit)}` | `ShareInfo`（201） |
| DELETE | `/cards/{id}/shares/{share_id}` | — | 204 |
| GET | `/cards/{id}/memos` | — | `{items: MemoRead[], can_create: boolean}`（作成日時の降順） |
| POST | `/cards/{id}/memos` | `{body}` | `MemoRead`（201） |
| PATCH | `/cards/{id}/memos/{memo_id}` | `{body}` | `MemoRead` |
| DELETE | `/cards/{id}/memos/{memo_id}` | — | 204 |

> 画像アップロード制約: 形式 `image/jpeg` `image/jpg` `image/png` `image/webp`、最大 15MB。
> 共有を受けた側（`shared=true`）は画像アップロード・タグ編集・名刺削除不可。`edit` 権限ではフィールド編集とメモ追加・自分のメモの編集／削除が可能。

メモの本文は前後の空白を除去して1〜5000文字。名刺所有者は全メモを管理でき、`edit` 共有先は追加と自分のメモの編集・削除、`view` 共有先は閲覧のみ。共有解除後は投稿者でもアクセス不可。変更は `card.memo_create` / `card.memo_update` / `card.memo_delete` として監査記録する（本文は監査ログに保存しない）。

### 🏷 タグ `/api/tags`

| Method | Path | Body | 返り値 |
|---|---|---|---|
| GET | `/tags` | — | `TagRead[]` |
| POST | `/tags` | `{name(1〜50字), color?(〜20字)}` | `TagRead`（201） |
| PATCH | `/tags/{id}` | `{name?, color?}` | `TagRead` |
| DELETE | `/tags/{id}` | — | 204 |

> タグはユーザー単位（`owner_id`）。同名重複は 400。

### 👤 ユーザー検索 `/api/users`

| Method | Path | パラメータ | 返り値 | 用途 |
|---|---|---|---|---|
| GET | `/users/search` | query `q`(2字以上) | `UserSummary[]`（最大 10 件） | 共有先選択 |

### 📤 エクスポート `/api/export`

| Method | Path | パラメータ | 返り値 |
|---|---|---|---|
| GET | `/export/cards` | query `format`(csv/vcard)・`scope`・`q`・`favorite`・`tag_id`・`ids[]` | ファイル（`cards.csv` / `cards.vcf`） |

> フィルタのセマンティクスは `/cards` と同一。`ids[]` 指定時はアクセス権のある名刺のみ通す。
> CSV は Excel 文字化け回避のため BOM 付き UTF-8。全エクスポートは `audit_logs(card.export)` に記録。

### 🔧 その他

| Method | Path | 認証 | 備考 |
|---|---|---|---|
| POST | `/api/search/reindex` | **admin 限定** | Meilisearch 全件再構築 → `{configured, indexed}` |
| POST | `/api/scanner/import` | `X-Scanner-Token` ヘッダ | スキャナ連携用（GUI からは使わない） |
| GET | `/healthz` | 不要 | 死活監視（`/api` なし）→ `{status: "ok"}` |

---

## 2. 画面に表示できるデータ構造

### 名刺 `CardDetail` / `CardSummary`

```ts
{
  id, owner_id, status, source,
  image_front_key, image_back_key,    // 画像有無の判定に使用（nullなら未アップロード）
  created_at, updated_at,
  fields: CardFieldsRead | null,
  tags: [{ id, name, color }],
  is_favorite: boolean,
  shared: boolean                     // 自分が共有を受けた名刺か
}
```

### 名刺フィールド `CardFieldsRead`

```ts
{
  // --- 編集可能な12項目 ---
  person_name, person_name_kana, company, department, title,
  postal_code, address, phone, mobile, fax, email, website,
  // --- 読み取り専用 ---
  latitude, longitude,    // 座標（地図表示用）
  raw_ocr_text,           // OCR 生テキスト（現UIは未表示）
  ocr_confidence          // { フィールド名: 0〜1 } 信頼度（現UIは未表示）
}
```

### 列挙値

- `status`: `uploaded` / `ocr_running` / `ocr_done` / `confirmed` / `archived`
- `source`: `upload` / `camera` / `scanner` / `manual` / `email`
- `permission`: `view` / `edit`
- `role`: `admin` / `member`

### その他の型

| 型 | フィールド |
|---|---|
| `CurrentUser` | `id, email, display_name, role` |
| `UserSummary` | `id, email, display_name, role` |
| `Tag` / `TagRead` | `id, name, color, created_at` |
| `ShareInfo` | `id, card_id, shared_by, shared_with, permission, created_at` |
| `MemoRead` | `id, card_id, author_id, author_name, body, created_at, can_edit, can_delete` |
| `PasskeyCredential` | `id, nickname, created_at, last_used_at` |
| `CardGeoPoint` | `id, person_name, company, address, latitude, longitude, shared` |
| `CardListResponse` | `items: CardSummary[], total: int` |
| `CardGeoResponse` | `items: CardGeoPoint[]` |

---

## 3. 現在のフロントエンド ページ構成（11 ページ）

| ルート | 役割 | 使用 API |
|---|---|---|
| `/` | 認証判定 → リダイレクト | `auth/me` |
| `/login` | パスワード＋パスキーログイン | `auth/login`, `webauthn/login/*` |
| `/register` | 新規登録 | `auth/register` |
| `/cards` | 一覧・検索・フィルタ・エクスポート | `cards`, `tags`, `export` |
| `/cards/[id]` | 詳細・編集・画像・OCR・共有・タグ・座標 | `cards/*` 全般, `tags` |
| `/cards/new` | 手動作成 | `cards`(POST) |
| `/scan` | 撮影 → OCR | `cards`(POST), `cards/{id}/image` |
| `/map` | 地図表示（MapLibre GL + OSM） | `cards/geo` |
| `/tags` | タグ管理 | `tags/*` |
| `/settings/passkeys` | パスキー管理 | `webauthn/credentials` |
| `/offline` | PWA オフラインフォールバック | — |

---

## 4. 作り直し時の重要メモ（未対応の機能・表示項目）

API や画面の追加が必要な機能・表示項目。

メモ機能は実装済み（名刺詳細画面と `/cards/{id}/memos` の CRUD API）。既存の `card_memos` テーブルを利用するため追加マイグレーションは不要。

1. **監査ログ閲覧** — `audit_logs` に全操作が記録されているが閲覧 API なし（管理画面を作るなら要追加）。
2. **管理者機能** — admin ロールはあるが、ユーザー一覧 / 招待 / ロール変更の API は `search/reindex` 以外なし。`/register` が実質オープン登録。
3. **OCR 信頼度・生テキストの可視化** — `ocr_confidence`・`raw_ocr_text` は API で返るのに現 UI は未表示。確認画面で「自信のないフィールドをハイライト」等に使える。
4. **パスワード変更・メール認証・招待リンク** — 計画にはあるが未実装。
5. **`scanned_at`・`geocoded_at`** — DB にはあるが読み取りスキーマ（`CardFieldsRead` / `CardSummary`）に含まれず API で返らない。
