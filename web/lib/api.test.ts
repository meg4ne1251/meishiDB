import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, cardsApi, exportApi } from "@/lib/api";

interface FakeInit {
  status?: number;
  body?: string;
  ok?: boolean;
}

function fakeResponse({ status = 200, body = "", ok }: FakeInit) {
  return {
    status,
    ok: ok ?? (status >= 200 && status < 300),
    text: async () => body,
  };
}

describe("api()", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mock(res: ReturnType<typeof fakeResponse>) {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(res);
  }

  function lastCall() {
    return (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.at(-1)!;
  }

  it("returns parsed JSON on success and hits /api/* on the client", async () => {
    mock(fakeResponse({ body: JSON.stringify({ hello: "world" }) }));
    const data = await api<{ hello: string }>("/auth/me");
    expect(data).toEqual({ hello: "world" });
    const [url] = lastCall();
    expect(url).toBe("/api/auth/me");
  });

  it("returns undefined for 204 No Content", async () => {
    mock(fakeResponse({ status: 204 }));
    const data = await api("/cards/x/favorite", { method: "POST" });
    expect(data).toBeUndefined();
  });

  it("serializes a JSON body and sets Content-Type", async () => {
    mock(fakeResponse({ body: "{}" }));
    await api("/cards", { method: "POST", body: { a: 1 } });
    const [, init] = lastCall();
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
  });

  it("passes raw bodies through without JSON encoding", async () => {
    mock(fakeResponse({ body: "{}" }));
    const fd = new FormData();
    fd.append("image", "x");
    await api("/cards/x/image", { method: "POST", body: fd, raw: true });
    const [, init] = lastCall();
    expect(init.body).toBe(fd);
    expect(new Headers(init.headers).get("content-type")).toBeNull();
  });

  it("forwards a cookie header (SSR)", async () => {
    mock(fakeResponse({ body: "{}" }));
    await api("/auth/me", { cookieHeader: "meishi_session=abc" });
    const [, init] = lastCall();
    expect(new Headers(init.headers).get("cookie")).toBe("meishi_session=abc");
  });

  it("throws ApiError with the detail field on error responses", async () => {
    mock(fakeResponse({ status: 400, body: JSON.stringify({ detail: "bad input" }) }));
    await expect(api("/cards")).rejects.toMatchObject({
      status: 400,
      detail: "bad input",
      message: "bad input",
    });
    await expect(api("/cards")).rejects.toBeInstanceOf(ApiError);
  });

  it("falls back to the raw payload when there is no detail field", async () => {
    mock(fakeResponse({ status: 500, body: JSON.stringify({ oops: true }) }));
    await expect(api("/cards")).rejects.toMatchObject({
      status: 500,
      detail: { oops: true },
    });
  });

  it("returns plain text when the body is not JSON", async () => {
    mock(fakeResponse({ body: "just text" }));
    const data = await api<string>("/whatever");
    expect(data).toBe("just text");
  });
});

describe("ApiError", () => {
  it("uses a string detail as the message", () => {
    expect(new ApiError(404, "not found").message).toBe("not found");
  });
  it("falls back to a generic message for non-string details", () => {
    expect(new ApiError(500, { x: 1 }).message).toBe("API error: 500");
  });
});

describe("query string building", () => {
  it("builds export URLs and repeats array params", () => {
    expect(exportApi.url({ format: "csv" })).toBe("/api/export/cards?format=csv");
    expect(exportApi.url({ format: "vcard", scope: "owned", ids: ["a", "b"] })).toBe(
      "/api/export/cards?format=vcard&scope=owned&ids=a&ids=b",
    );
  });

  it("omits empty-string params", () => {
    // thumb=false -> "" は除外される
    expect(cardsApi.imageUrl("ID", "front", false)).toBe("/api/cards/ID/image?side=front");
    expect(cardsApi.imageUrl("ID", "front", true)).toBe(
      "/api/cards/ID/image?side=front&thumb=true",
    );
  });
});
