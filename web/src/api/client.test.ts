import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, api, resetSessionForTests } from "./client";

function mockFetch(routes: Record<string, { status: number; body: unknown }>) {
  return vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input);
    const route = routes[path];
    if (!route) throw new Error(`unexpected fetch: ${path}`);
    return {
      ok: route.status >= 200 && route.status < 300,
      status: route.status,
      json: async () => route.body,
    } as Response;
  });
}

describe("api client", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
  });

  it("bootstraps the token once and sends it on requests", async () => {
    const fetchMock = mockFetch({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/topics": { status: 200, body: { topics: [] } },
    });
    vi.stubGlobal("fetch", fetchMock);

    await api("/v1/topics");
    await api("/v1/topics");

    const sessionCalls = fetchMock.mock.calls.filter(([u]) => String(u) === "/v1/session");
    expect(sessionCalls).toHaveLength(1);
    const topicCall = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/topics");
    expect((topicCall![1] as RequestInit).headers).toMatchObject({ "X-EP-Token": "tok" });
  });

  it("throws ApiRequestError with the server's code on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/nope": {
          status: 404,
          body: { error: { code: "not_found", message: "no run" } },
        },
      }),
    );
    const err = (await api("/v1/runs/nope").catch((e) => e)) as ApiRequestError;
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("no run");
  });
});
