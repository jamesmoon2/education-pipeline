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
  getConfigProviders,
  getConfigCatalog,
  getConfigPlan,
  putConfigPlan,
  getRunPlan,
  getProfile,
  getProfiles,
  previewProfile,
  putProfile,
  duplicateProfile,
  getPersonalization,
  prepareAudit,
  postAuditResponse,
  approveAudit,
  enqueueAuditJob,
} from "./client";
import { metadataNumber } from "./types";
import type { LearnerProfile } from "./types";

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
  routes: Record<string, { status: number; body: unknown; rawBody?: string }>,
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
      text: async () => route.rawBody ?? JSON.stringify(route.body),
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

describe("personalization audit adapters", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetches the typed personalization aggregate", async () => {
    const payload = {
      topic_id: "topic/a",
      profile: { state: "not_attached", id: null },
      trace: { state: "missing", goals: [], facets: [] },
      audit: {
        state: "not_run",
        stage_state: "not_run",
        available: false,
        unavailable_reason: "No learner profile is attached.",
        findings: [],
      },
      findings: [
        {
          id: "personalization.goal_uncovered:goal-001",
          rule_id: "personalization.goal_uncovered",
          severity: "warning",
          blocking: false,
          waivable: true,
          path: "",
          message: "An authoritative learner goal is not served or validly excluded.",
          remediation: "Serve the goal or add a valid exclusion.",
          stage: "draft",
        },
      ],
      export: { state: "missing" },
    };
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/runs/topic%2Fa/personalization": { status: 200, body: payload },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getPersonalization("topic/a");

    expect(result).toEqual(payload);
    expect(result.findings[0]?.rule_id).toBe("personalization.goal_uncovered");
  });

  it("uses exact audit action routes and bodies", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/runs/topic%2Fa/audit": { status: 200, body: { topic_id: "topic/a", stage: "audit" } },
      "/v1/runs/topic%2Fa/stages/audit/response": {
        status: 200,
        body: { topic_id: "topic/a", stage: "audit", response_path: "responses/audit.response.json" },
      },
      "/v1/runs/topic%2Fa/stages/audit/approve": {
        status: 200,
        body: { topic_id: "topic/a", stage: "audit", approved_path: "approved/audit.json" },
      },
      "/v1/jobs": { status: 200, body: { id: "job-1", topic_id: "topic/a", stage: "audit" } },
    });
    vi.stubGlobal("fetch", fetchMock);

    await prepareAudit("topic/a", true);
    await postAuditResponse("topic/a", "{}", true);
    await approveAudit("topic/a", true);
    await enqueueAuditJob("topic/a", true);

    const bodies = Object.fromEntries(
      fetchMock.mock.calls
        .filter(([, init]) => init?.body)
        .map(([url, init]) => [String(url), JSON.parse(init!.body as string)]),
    );
    expect(bodies).toEqual({
      "/v1/runs/topic%2Fa/audit": { rebuild: true },
      "/v1/runs/topic%2Fa/stages/audit/response": { text: "{}", force: true },
      "/v1/runs/topic%2Fa/stages/audit/approve": { overwrite: true },
      "/v1/jobs": { topic_id: "topic/a", stage: "audit", force: true },
    });
  });
});

describe("config endpoints", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("getConfigProviders fetches provider availability", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/config/providers": {
        status: 200,
        body: {
          providers: [
            {
              id: "claude",
              label: "Claude",
              description: "Claude Code",
              executable: true,
              available: true,
              reason: null,
            },
          ],
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getConfigProviders();

    expect(result.providers).toHaveLength(1);
    const call = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/config/providers");
    expect(call).toBeDefined();
    expect((call![1] as RequestInit | undefined)?.method ?? "GET").toBe("GET");
  });

  it("getConfigCatalog fetches the model catalog", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/config/catalog": {
        status: 200,
        body: {
          providers: [
            {
              id: "claude",
              label: "Claude",
              description: "Claude Code",
              models: [
                {
                  id: "sonnet",
                  label: "Sonnet",
                  description: "Balanced",
                  quality: "high",
                  default_effort: "medium",
                },
              ],
            },
          ],
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getConfigCatalog();

    expect(result.providers[0].models[0].id).toBe("sonnet");
    const call = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/config/catalog");
    expect(call).toBeDefined();
  });

  it("getConfigPlan fetches the effective plan", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/config/plan": {
        status: 200,
        body: {
          provider: "claude",
          plan_sha256: "hash-1",
          stages: [
            {
              stage: "spec",
              provider: "claude",
              model: "sonnet",
              effort: "medium",
              recommendation: "default",
              warning: null,
              source: "default",
              command: null,
            },
          ],
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getConfigPlan();

    expect(result.plan_sha256).toBe("hash-1");
    const call = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/config/plan");
    expect(call).toBeDefined();
  });

  it("putConfigPlan sends a JSON PUT with base_sha256, provider, and stages", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/config/plan": {
        status: 200,
        body: {
          provider: "claude",
          plan_sha256: "hash-2",
          stages: [],
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await putConfigPlan("hash-1", "claude", {
      spec: { provider: "codex", model: "gpt-5", effort: "high" },
    });

    expect(result.plan_sha256).toBe("hash-2");
    const call = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/config/plan");
    const init = call![1] as RequestInit;
    expect(init.method).toBe("PUT");
    expect(init.headers).toMatchObject({
      "X-EP-Token": "tok",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(init.body as string)).toEqual({
      base_sha256: "hash-1",
      provider: "claude",
      stages: {
        spec: { provider: "codex", model: "gpt-5", effort: "high" },
      },
    });
  });

  it("getRunPlan fetches the per-run effective plan", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/runs/topic-a/plan": {
        status: 200,
        body: {
          provider: "claude",
          plan_sha256: "hash-3",
          stages: [],
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getRunPlan("topic-a");

    expect(result.plan_sha256).toBe("hash-3");
    const call = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/runs/topic-a/plan");
    expect(call).toBeDefined();
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

const structuredProfile: LearnerProfile = {
  schema_version: 1,
  id: "learner-a",
  target_learner: "A synthetic learner",
  adjacent_domains: [],
  learning_goals: ["Understand systems"],
  preferred_examples: [],
  examples_to_avoid: [],
  assessment_styles: [],
  accessibility_constraints: [],
  sensitive_areas: [],
  learning_preferences: {
    preferred_modalities: [],
    preferred_visual_aids: [],
    practice_style: [],
    common_sticking_points: [],
    attention_constraints: [],
    review_style: [],
  },
  localization: {},
  privacy: { private_by_default: true, include_in_published_output: false },
  metadata: { cohort: { year: 2026 }, active: true },
};

describe("profile endpoints", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses the structured list and detail endpoints", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/profiles": {
        status: 200,
        body: { profiles: [{ id: "learner-a", attached_topic_count: 2 }] },
      },
      "/v1/profiles/learner-a": {
        status: 200,
        body: {
          id: "learner-a",
          parsed: structuredProfile,
          sensitivity: { target_learner: "high" },
          content_sha256: "sha-1",
          warnings: [],
          attached_topic_count: 2,
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    expect((await getProfiles()).profiles[0]).toEqual({
      id: "learner-a",
      attached_topic_count: 2,
    });
    expect((await getProfile("learner-a")).content_sha256).toBe("sha-1");
  });

  it("previews, creates, updates, and duplicates structured profiles", async () => {
    const detail = {
      id: "learner-a",
      parsed: structuredProfile,
      sensitivity: { target_learner: "high" },
      content_sha256: "sha-2",
      warnings: [],
      attached_topic_count: 0,
    };
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/profiles/preview": {
        status: 200,
        body: { ...detail, prompt_context: "# Learner Profile Context", publishable_summary: null },
      },
      "/v1/profiles/learner-a": { status: 200, body: detail },
      "/v1/profiles/learner-a/duplicate": {
        status: 201,
        body: { ...detail, id: "learner-copy", parsed: { ...structuredProfile, id: "learner-copy" } },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    await previewProfile(structuredProfile);
    await putProfile("learner-a", structuredProfile, null);
    await putProfile("learner-a", structuredProfile, "sha-1");
    await duplicateProfile("learner-a", "learner-copy");

    const calls = fetchMock.mock.calls.filter(([url]) => String(url) !== "/v1/session");
    expect(JSON.parse((calls[0][1] as RequestInit).body as string)).toEqual({ profile: structuredProfile });
    expect(JSON.parse((calls[1][1] as RequestInit).body as string)).toEqual({
      profile: structuredProfile,
      base_sha256: null,
    });
    expect(JSON.parse((calls[2][1] as RequestInit).body as string)).toEqual({
      profile: structuredProfile,
      base_sha256: "sha-1",
    });
    expect(JSON.parse((calls[3][1] as RequestInit).body as string)).toEqual({ new_id: "learner-copy" });
  });

  it("preserves safe structured conflict details", async () => {
    vi.stubGlobal("fetch", mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/profiles/learner-a": {
        status: 409,
        body: {
          error: {
            code: "stale_content",
            message: "reload profiles before retrying",
            details: { current_sha256: "sha-current" },
          },
        },
      },
    }));

    const error = await putProfile("learner-a", structuredProfile, "sha-old").catch((value) => value) as ApiRequestError;
    expect(error.status).toBe(409);
    expect(error.details).toEqual({ current_sha256: "sha-current" });
  });

  it("round-trips exact metadata numeric text without changing the HTTP contract", async () => {
    const rawDetail = JSON.stringify({
      id: "learner-a", parsed: structuredProfile, sensitivity: {}, content_sha256: "sha", warnings: [], attached_topic_count: 0,
    }).replace('"year":2026', '"year":2.0');
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/profiles/learner-a": { status: 200, body: {}, rawBody: rawDetail },
    });
    vi.stubGlobal("fetch", fetchMock);

    const loaded = await getProfile("learner-a");
    await putProfile("learner-a", loaded.parsed, "sha");

    const body = String((fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[1] as RequestInit).body);
    expect(body).toContain('"year":2.0');
    expect(JSON.parse(body)).toEqual({
      profile: expect.objectContaining({ id: "learner-a", metadata: expect.objectContaining({ cohort: { year: 2 } }) }),
      base_sha256: "sha",
    });
  });

  it("serializes switched numeric kinds, exponents, and boundary integers verbatim", async () => {
    const exactProfile: LearnerProfile = {
      ...structuredProfile,
      metadata: {
        integerToFloat: metadataNumber("2.0", "float"),
        floatToInteger: metadataNumber("2", "integer"),
        exponent: metadataNumber("-2.5e+3", "float"),
        minI64: metadataNumber("-9223372036854775808", "integer"),
        maxI64: metadataNumber("9223372036854775807", "integer"),
      },
    };
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/profiles/learner-a": { status: 200, body: { ...structuredProfile, parsed: exactProfile } },
    });
    vi.stubGlobal("fetch", fetchMock);

    await putProfile("learner-a", exactProfile, null);

    const body = String((fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[1] as RequestInit).body);
    expect(body).toContain('"integerToFloat":2.0');
    expect(body).toContain('"floatToInteger":2');
    expect(body).toContain('"exponent":-2.5e+3');
    expect(body).toContain('"minI64":-9223372036854775808');
    expect(body).toContain('"maxI64":9223372036854775807');
  });

  it("preserves legal metadata objects whose keys resemble the internal number wrapper", async () => {
    const collision = { rawJsonNumber: true, source: "user-authored", nested: { value: 3 } };
    const rawDetail = JSON.stringify({
      id: "learner-a",
      parsed: { ...structuredProfile, metadata: { collision } },
      sensitivity: {},
      content_sha256: "sha",
      warnings: [],
      attached_topic_count: 0,
    });
    vi.stubGlobal("fetch", mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/profiles/learner-a": { status: 200, body: {}, rawBody: rawDetail },
    }));

    const loaded = await getProfile("learner-a");

    expect(loaded.parsed.metadata.collision).toEqual({
      rawJsonNumber: true,
      source: "user-authored",
      nested: { value: expect.objectContaining({ kind: "integer", text: "3" }) },
    });
  });

  it("refuses to serialize an invalid numeric draft instead of coercing it to zero", () => {
    const invalidProfile: LearnerProfile = {
      ...structuredProfile,
      metadata: { count: metadataNumber("-", "integer") },
    };

    expect(() => putProfile("learner-a", invalidProfile, "sha")).toThrow("Invalid integer metadata value");
  });
});
