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

describe("Stop", () => {
  it("says plainly what stopping did", async () => {
    const { stopMessage } = await import("./upload");
    expect(stopMessage("cancelled")).toMatch(/never loaded/);
    expect(stopMessage("running")).toMatch(/running on the server.*records are deleted/);
    expect(stopMessage("cleared")).toMatch(/cleaned up/);
    expect(stopMessage("finished")).toMatch(/already finished/);
  });

  it("blocks new uploads while it is still cleaning up", async () => {
    const { isBusy } = await import("./upload");
    expect(isBusy({ phase: "stopped", name: "u.csv", message: "", cleaning: true })).toBe(true);
    expect(isBusy({ phase: "stopped", name: "u.csv", message: "" })).toBe(false);
    expect(isBusy({ phase: "sending", name: "u.csv", bytes: 1 })).toBe(true);
    expect(isBusy({ phase: "idle" })).toBe(false);
  });
});

describe("clearing an earlier upload", () => {
  afterEach(() => vi.restoreAllMocks());

  it("waits for a running match to finish, then deletes its records", async () => {
    const { api } = await import("../api/client");
    const { clearUpload } = await import("./upload");
    const order: string[] = [];
    vi.spyOn(api, "cancelUpload").mockImplementation(async () => (order.push("stop"), { job_id: "j", outcome: "running" }));
    vi.spyOn(api, "upload").mockImplementation(async () => (order.push("poll"), progress({ notifications: { sent: 5 } })));
    vi.spyOn(api, "purgeUpload").mockImplementation(async () => (order.push("delete"), { deleted_users: 10, remaining: 0 }));
    const said: string[] = [];
    await clearUpload("j", (s) => said.push(s));
    expect(order).toEqual(["stop", "poll", "delete"]);
    expect(said.join(" ")).toMatch(/matching on the server/);
  });

  it("deletes straight away when the file was never loaded or the run is over", async () => {
    const { api } = await import("../api/client");
    const { clearUpload } = await import("./upload");
    const poll = vi.spyOn(api, "upload");
    const purge = vi.spyOn(api, "purgeUpload").mockResolvedValue({ deleted_users: 0, remaining: 0 });
    for (const outcome of ["cancelled", "finished", "stopped"]) await clearUpload("j", () => {}, outcome);
    expect(poll).not.toHaveBeenCalled();
    expect(purge).toHaveBeenCalledTimes(3);
  });
});
