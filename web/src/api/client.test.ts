import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiRequestError,
  api,
  apiPost,
  download,
  postPreview,
  postGuidePreview,
  postValidate,
  getValidation,
  postWaiver,
  postResponse,
  putResponse,
  resetSessionForTests,
} from "./client";

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

function mockFetchWithInit(
  routes: Record<string, { status: number; body: unknown }>,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const route = routes[path];
    if (!route) throw new Error(`unexpected fetch: ${path}`);
    void init;
    return {
      ok: route.status >= 200 && route.status < 300,
      status: route.status,
      json: async () => route.body,
    } as Response;
  });
}

describe("apiPost", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends a JSON POST with the token header", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/runs/t/stages/draft/response": {
        status: 200,
        body: { topic_id: "t", stage: "draft", response_path: "responses/draft.response.md" },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    await postResponse("t", "draft", "hello");

    const call = fetchMock.mock.calls.find(
      ([u]) => String(u) === "/v1/runs/t/stages/draft/response",
    );
    const init = call![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "X-EP-Token": "tok",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(init.body as string)).toEqual({ text: "hello", force: false });
  });

  it("maps the error envelope, preserving 409 conflict codes", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchWithInit({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/t/finalize": {
          status: 409,
          body: { error: { code: "already_exists", message: "run is already finalized" } },
        },
      }),
    );
    const err = (await apiPost("/v1/runs/t/finalize", {}).catch((e: unknown) => e)) as ApiRequestError;
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("already_exists");
  });
});

describe("download", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetches with auth and clicks a temporary object-URL anchor", async () => {
    const blob = new Blob(["guide body"]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
        if (String(input) === "/v1/session") {
          return {
            ok: true,
            status: 200,
            json: async () => ({ token: "tok", version: "0.1.0" }),
          } as Response;
        }
        return {
          ok: true,
          status: 200,
          blob: async () => blob,
          json: async () => ({}),
        } as unknown as Response;
      }),
    );
    const createObjectURL = vi.fn(() => "blob:fake");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    await download("/v1/runs/t/final/download", "t-guide.md");

    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
  });

  it("throws ApiRequestError from the envelope on failure", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchWithInit({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/t/final/download": {
          status: 404,
          body: { error: { code: "not_found", message: "run 't' is not finalized" } },
        },
      }),
    );
    const err = (await download("/v1/runs/t/final/download", "t-guide.md").catch(
      (e: unknown) => e,
    )) as ApiRequestError;
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
  });
});

describe("apiPut", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("putResponse sends a JSON PUT with text and base_sha256", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/runs/t/stages/draft/response": {
        status: 200,
        body: {
          topic_id: "t",
          stage: "draft",
          response_path: "responses/draft.response.md",
          response_sha256: "hash-2",
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await putResponse("t", "draft", "new body", "hash-1");

    expect(result.response_sha256).toBe("hash-2");
    const call = fetchMock.mock.calls.find(
      ([u]) => String(u) === "/v1/runs/t/stages/draft/response",
    );
    const init = call![1] as RequestInit;
    expect(init.method).toBe("PUT");
    expect(init.headers).toMatchObject({
      "X-EP-Token": "tok",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(init.body as string)).toEqual({
      text: "new body",
      base_sha256: "hash-1",
    });
  });

  it("surfaces the stale_content conflict code", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchWithInit({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/t/stages/draft/response": {
          status: 409,
          body: { error: { code: "stale_content", message: "changed on disk" } },
        },
      }),
    );
    const err = (await putResponse("t", "draft", "x", "old").catch(
      (e: unknown) => e,
    )) as ApiRequestError;
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("stale_content");
  });

  it("postPreview posts text and returns html", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/preview": { status: 200, body: { html: "<h1>Hi</h1>" } },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await postPreview("# Hi");

    expect(result.html).toBe("<h1>Hi</h1>");
    const call = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/preview");
    expect(JSON.parse((call![1] as RequestInit).body as string)).toEqual({
      text: "# Hi",
    });
  });

  it("posts guide preview, validation, findings, and waiver payloads", async () => {
    const report = {
      report_schema_version: 1,
      guide_schema_version: "1.0",
      phase: "draft",
      guide_sha256: "hash",
      validator_version: "1",
      summary: { blocking: 0, errors: 0, warnings: 0, info: 0 },
      findings: [],
    };
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/guide-preview": {
        status: 200,
        body: { html: "<!doctype html>", content_sha256: "hash", validation: report.summary },
      },
      "/v1/runs/t/validate": { status: 200, body: { state: "current", report } },
      "/v1/runs/t/validation/draft": { status: 200, body: { state: "current", report } },
      "/v1/runs/t/validation/draft/waivers": {
        status: 200,
        body: {
          state: "current",
          report,
          waivers: { schema_version: 1, guide_sha256: "hash", waivers: [] },
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    await postGuidePreview("{}");
    await postValidate("t", "draft");
    await getValidation("t", "draft");
    await postWaiver("t", "draft", "finding", "hash", "accepted");

    const bodies = Object.fromEntries(
      fetchMock.mock.calls
        .filter(([, init]) => init?.body)
        .map(([url, init]) => [String(url), JSON.parse(init!.body as string)]),
    );
    expect(bodies["/v1/guide-preview"]).toEqual({ text: "{}", include_validation: true });
    expect(bodies["/v1/runs/t/validate"]).toEqual({ phase: "draft" });
    expect(bodies["/v1/runs/t/validation/draft/waivers"]).toEqual({
      finding_id: "finding",
      guide_sha256: "hash",
      reason: "accepted",
    });
  });
});
