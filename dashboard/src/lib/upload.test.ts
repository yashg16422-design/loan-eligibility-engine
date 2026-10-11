import { afterEach, describe, expect, it, vi } from "vitest";
import { stages } from "../components/WorkflowMap";
import type { UploadProgress } from "../api/types";
import { isFinished, resumed } from "./upload";

afterEach(() => vi.unstubAllGlobals());

const progress = (over: Partial<UploadProgress> = {}): UploadProgress =>
  ({
    job: { status: "COMPLETED", match_status: "DONE", total_rows: 10, inserted: 10, updated: 0, unchanged: 0, rejected: 0 },
    rejects: [],
    match_run: { status: "done", matches_new: 40, naive_pairs: 590, classes: 6, llm_calls: 0 },
    notifications: {},
    ...over,
  }) as unknown as UploadProgress;

describe("an upload survives a reload", () => {
  it("picks the tracked job up again from this tab's storage", () => {
    const saved = { jobId: "job-1", name: "users.csv", bytes: 10, startedAt: 1 };
    vi.stubGlobal("sessionStorage", { getItem: () => JSON.stringify(saved) });
    expect(resumed()).toEqual({ phase: "tracking", ...saved, finished: false });
  });

  it("starts idle when nothing was being tracked, or storage is unavailable", () => {
    vi.stubGlobal("sessionStorage", { getItem: () => null });
    expect(resumed()).toEqual({ phase: "idle" });
    vi.stubGlobal("sessionStorage", { getItem: () => { throw new Error("private mode"); } });
    expect(resumed()).toEqual({ phase: "idle" });
  });
});

describe("the email step", () => {
  const tracking = (p: UploadProgress) => ({ phase: "tracking" as const, name: "u.csv", bytes: 1, jobId: "j", startedAt: 0, finished: false, progress: p });

  it("says the sweeper is finishing a run that n8n dropped after matching", () => {
    const p = progress({ match_run: { status: "failed", matches_new: 40 } as UploadProgress["match_run"] });
    const notify = stages(tracking(p)).find((s) => s.key === "notify")!;
    expect(notify.status).toBe("active");
    expect(notify.lines.join(" ")).toMatch(/sweeper/);
    expect(isFinished(p)).toBe(false); // keeps tracking until the emails are recorded
  });

  it("is done once the emails are recorded", () => {
    const p = progress({ notifications: { sent: 5, skipped_demo: 5 } });
    expect(stages(tracking(p)).find((s) => s.key === "notify")!.status).toBe("done");
    expect(isFinished(p)).toBe(true);
  });
});
