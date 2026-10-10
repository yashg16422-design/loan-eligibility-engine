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
