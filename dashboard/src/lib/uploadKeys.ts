// The delete key POST /uploads hands to the browser that created an upload. Kept in this
// browser only: it is what lets you delete your own uploads without an admin account. If it is
// lost (another browser, cleared storage), only an admin can delete that upload.
const STORE = "clickpar-upload-keys";

function read(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(STORE) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

export const uploadKeys = {
  get: (jobId: string): string | undefined => read()[jobId],
  set: (jobId: string, key: string) => {
    try {
      localStorage.setItem(STORE, JSON.stringify({ ...read(), [jobId]: key }));
    } catch {
      /* private mode: deleting this upload will need an admin */
    }
  },
};
