/**
 * Server / Client から共通で使う fetch ラッパー。
 *
 * - 開発時: ブラウザは `/api/*` 経由で Next.js の rewrite を通って FastAPI に到達する。
 * - サーバーサイド (RSC) では NEXT_PUBLIC_API_URL を直接叩く。
 */

import type {
  Card,
  CardListResponse,
  CurrentUser,
  PasskeyCredential,
  ShareInfo,
  Tag,
  UserSummary,
} from "@/lib/types";

const SERVER_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function isServer() {
  return typeof window === "undefined";
}

function endpoint(path: string) {
  if (isServer()) {
    return `${SERVER_API}/api${path}`;
  }
  return `/api${path}`;
}

interface FetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  cookieHeader?: string;
  raw?: boolean; // body を JSON 化せずそのまま渡す（FormData 等）
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `API error: ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T = unknown>(path: string, opts: FetchOptions = {}): Promise<T> {
  const { body, cookieHeader, headers, raw, ...rest } = opts;
  const finalHeaders = new Headers(headers);
  let payloadBody: BodyInit | undefined;
  if (raw) {
    payloadBody = body as BodyInit;
  } else if (body !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    payloadBody = JSON.stringify(body);
  }
  if (cookieHeader) {
    finalHeaders.set("cookie", cookieHeader);
  }

  const res = await fetch(endpoint(path), {
    ...rest,
    headers: finalHeaders,
    credentials: "include",
    cache: "no-store",
    body: payloadBody,
  });

  if (res.status === 204) return undefined as T;

  let payload: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    throw new ApiError(res.status, detail);
  }
  return payload as T;
}

// ---- Auth ----
export const authApi = {
  me: (cookieHeader?: string) => api<CurrentUser>("/auth/me", { cookieHeader }),
  login: (email: string, password: string) =>
    api<CurrentUser>("/auth/login", { method: "POST", body: { email, password } }),
  register: (email: string, display_name: string, password: string) =>
    api<CurrentUser>("/auth/register", {
      method: "POST",
      body: { email, display_name, password },
    }),
  logout: () => api<{ ok: boolean }>("/auth/logout", { method: "POST" }),
};

// ---- WebAuthn / Passkey ----
export const webauthnApi = {
  registerBegin: () =>
    api<{ challenge_id: string; options: PublicKeyCredentialCreationOptionsJSON }>(
      "/webauthn/register/begin",
      { method: "POST" },
    ),
  registerFinish: (body: {
    challenge_id: string;
    credential: unknown;
    nickname?: string;
  }) => api<{ id: string; nickname: string }>("/webauthn/register/finish", { method: "POST", body }),
  loginBegin: (email?: string) =>
    api<{ challenge_id: string; options: PublicKeyCredentialRequestOptionsJSON }>(
      "/webauthn/login/begin",
      { method: "POST", body: email ? { email } : {} },
    ),
  loginFinish: (body: { challenge_id: string; credential: unknown }) =>
    api<CurrentUser>("/webauthn/login/finish", { method: "POST", body }),
  list: () => api<PasskeyCredential[]>("/webauthn/credentials"),
  remove: (id: string) =>
    api<void>(`/webauthn/credentials/${id}`, { method: "DELETE" }),
};

// SimpleWebAuthn 由来の型（同等の最小型のみ宣言、実体は any 互換）
type PublicKeyCredentialCreationOptionsJSON = Record<string, unknown>;
type PublicKeyCredentialRequestOptionsJSON = Record<string, unknown>;

// ---- Cards ----
export interface ListCardsParams {
  scope?: "owned" | "shared" | "all";
  q?: string;
  favorite?: boolean;
  tag_id?: string;
  limit?: number;
  offset?: number;
}

function qsFor(params: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (Array.isArray(v)) {
      v.forEach((x) => qs.append(k, String(x)));
    } else if (v !== undefined && v !== null && v !== "") {
      qs.set(k, String(v));
    }
  });
  return qs.toString() ? `?${qs}` : "";
}

export const cardsApi = {
  list: (params: ListCardsParams = {}, cookieHeader?: string) =>
    api<CardListResponse>(`/cards${qsFor(params as Record<string, unknown>)}`, { cookieHeader }),
  get: (id: string, cookieHeader?: string) => api<Card>(`/cards/${id}`, { cookieHeader }),
  create: (body: {
    source?: string;
    fields?: Partial<Card["fields"]>;
    tag_ids?: string[];
  }) => api<Card>("/cards", { method: "POST", body }),
  update: (
    id: string,
    body: {
      status?: string;
      fields?: Partial<Card["fields"]>;
      tag_ids?: string[];
    },
  ) => api<Card>(`/cards/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api<void>(`/cards/${id}`, { method: "DELETE" }),

  uploadImage: async (
    id: string,
    file: Blob,
    opts: { side?: "front" | "back"; runOcr?: boolean; filename?: string } = {},
  ) => {
    const fd = new FormData();
    fd.append("image", file, opts.filename ?? "card.jpg");
    fd.append("side", opts.side ?? "front");
    fd.append("run_ocr", opts.runOcr === false ? "false" : "true");
    return api<Card>(`/cards/${id}/image`, { method: "POST", body: fd, raw: true });
  },
  rerunOcr: (id: string) => api<Card>(`/cards/${id}/ocr`, { method: "POST" }),
  imageUrl: (id: string, side: "front" | "back" = "front", thumb = false) =>
    `/api/cards/${id}/image${qsFor({ side, thumb: thumb ? "true" : "" })}`,

  favorite: (id: string, on: boolean) =>
    api<void>(`/cards/${id}/favorite`, { method: on ? "POST" : "DELETE" }),
  listShares: (id: string) => api<ShareInfo[]>(`/cards/${id}/shares`),
  share: (id: string, body: { user_email: string; permission: "view" | "edit" }) =>
    api<ShareInfo>(`/cards/${id}/shares`, { method: "POST", body }),
  unshare: (id: string, share_id: string) =>
    api<void>(`/cards/${id}/shares/${share_id}`, { method: "DELETE" }),
};

// ---- Export ----
export interface ExportParams {
  format: "csv" | "vcard";
  scope?: "owned" | "shared" | "all";
  q?: string;
  favorite?: boolean;
  tag_id?: string;
  ids?: string[];
}

export const exportApi = {
  url: (p: ExportParams) => `/api/export/cards${qsFor(p as Record<string, unknown>)}`,
};

// ---- Tags ----
export const tagsApi = {
  list: (cookieHeader?: string) => api<Tag[]>("/tags", { cookieHeader }),
  create: (body: { name: string; color?: string | null }) =>
    api<Tag>("/tags", { method: "POST", body }),
  update: (id: string, body: { name?: string; color?: string | null }) =>
    api<Tag>(`/tags/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api<void>(`/tags/${id}`, { method: "DELETE" }),
};

// ---- Users ----
export const usersApi = {
  search: (q: string) =>
    api<UserSummary[]>(`/users/search?q=${encodeURIComponent(q)}`),
};
