import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./client";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("API client retries", () => {
  it("retries a GET through a 5xx blip", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValueOnce(json(503, { error: "busy" })).mockResolvedValueOnce(json(200, []));
    vi.stubGlobal("fetch", fetch);
    const runs = api.runs();
    await vi.runAllTimersAsync();
    await expect(runs).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("never retries a write (a check must not be submitted twice)", async () => {
    const fetch = vi.fn().mockResolvedValue(json(500, { error: "internal error" }));
    vi.stubGlobal("fetch", fetch);
    await expect(
      api.check({ monthly_income: 50000, credit_score: 700, age: 30, employment_status: "salaried" }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("gives up after two retries with the server's message", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValue(json(503, { error: "the database is briefly unavailable" }));
    vi.stubGlobal("fetch", fetch);
    const runs = api.runs().catch((e: ApiError) => e);
    await vi.runAllTimersAsync();
    const err = await runs;
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toContain("briefly unavailable");
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});

describe("merchant calls carry the sign-in", () => {
  it("sends the Cognito ID token on every /uploads call (the gateway refuses them otherwise)", async () => {
    const { auth } = await import("./auth");
    vi.spyOn(auth, "idToken").mockResolvedValue("id-token");
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(json(200, [])));
    vi.stubGlobal("fetch", fetch);
    await api.uploads();
    await api.upload("job-1");
    await api.createUpload("users.csv");
    await api.purgeUpload("job-1");
    await api.uploadAnalytics("job-1");
    await api.emailPreviews("job-1");
    const sent = fetch.mock.calls.map(([path, init]) => [path, new Headers((init as RequestInit).headers).get("authorization")]);
    expect(sent).toEqual([
      ["/uploads", "Bearer id-token"],
      ["/uploads/job-1", "Bearer id-token"],
      ["/uploads", "Bearer id-token"],
      ["/uploads/job-1", "Bearer id-token"],
      ["/uploads/job-1/analytics", "Bearer id-token"],
      ["/uploads/job-1/emails", "Bearer id-token"],
    ]);
  });

  it("asks the public analytics route for nothing but the reference dataset, without a token", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(json(200, {})));
    vi.stubGlobal("fetch", fetch);
    await api.analytics("ref-job");
    const [path, init] = fetch.mock.calls[0];
    expect(path).toBe("/analytics?job_id=ref-job");
    expect(new Headers((init as RequestInit).headers).get("authorization")).toBeNull();
  });

  it("turns the gateway's bare 401 into what to do next", async () => {
    const { explain } = await import("./client");
    expect(explain(401, "Unauthorized")).toBe("Your sign-in has expired. Sign in again to continue.");
    expect(explain(429)).toMatch(/daily limit/);
    expect(explain(400, "body must be JSON")).toBe("body must be JSON");
  });
});

describe("big deletes", () => {
  it("keeps deleting in chunks until nothing is left, adding up the totals", async () => {
    const { untilDone } = await import("./client");
    const answers = [
      { deleted_users: 4000, remaining: 6000 },
      { deleted_users: 4000, remaining: 2000 },
      { deleted_users: 2000, remaining: 0 },
    ];
    const seen: number[][] = [];
    const r = await untilDone(async () => answers.shift()!, (d, left) => seen.push([d, left]));
    expect(r.deleted_users).toBe(10000);
    expect(seen).toEqual([[4000, 6000], [8000, 2000], [10000, 0]]);
  });

  it("works with a server that answers in one go (no remaining field)", async () => {
    const { untilDone } = await import("./client");
    expect((await untilDone(async () => ({ deleted_users: 7 }))).deleted_users).toBe(7);
  });
});
