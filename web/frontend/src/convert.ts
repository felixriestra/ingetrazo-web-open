/**
 * Import and export through the server's conversion jobs.
 *
 * A job runs in its own process on the server; this polls its status, shows progress
 * with a Cancel button, and then either opens the new document (import) or offers the
 * file (export).
 */
import {responseApiError} from "./api";
import {askChoice, askText, notice} from "./dialogs";
import {prefs} from "./prefs";

interface Job {id: string; status: "queued" | "running" | "completed" | "failed" | "cancelled"; progress: number; message: string;
  result: {document_id?: string; document_name?: string} | null; artifact: string | null}

const IMPORT_TYPES = ".obj,.stl,.dae,.dxf,.glb,.gltf,.skp";
export const EXPORT_FORMATS: [string, string][] = [
  ["glb", "GLB (glTF binary)"], ["gltf", "glTF (zip: json + bin)"], ["obj", "OBJ (zip with materials)"], ["stl", "STL"],
  ["dae", "COLLADA (.dae)"], ["dxf", "DXF (plan edges)"], ["svg", "SVG (plan edges, layers, 1:100)"], ["ifc", "IFC4"],
  // SKP export is commented out in the open-source release (the writer is private-edition only):
  // ["skp", "SketchUp (.skp)"],
];

/** The formats this server can export (SKP only exists in the private edition). */
async function availableExports(): Promise<[string, string][]> {
  try {
    const capabilities = await (await fetch("/api/v1/capabilities")).json() as {interoperability?: {exports?: string[]}};
    const offered = capabilities.interoperability?.exports;
    if (offered) return EXPORT_FORMATS.filter(([key]) => offered.includes(key));
  } catch { /* offer the common ones */ }
  return EXPORT_FORMATS.filter(([key]) => key !== "skp");
}

/** Show a job's progress until it ends; resolves the final job record. */
function follow(title: string, first: Job): Promise<Job> {
  return new Promise(resolve => {
    const dialog = document.createElement("dialog");
    dialog.className = "shortcut-dialog";
    const heading = Object.assign(document.createElement("h2"), {textContent: title});
    const message = Object.assign(document.createElement("p"), {className: "muted"});
    const bar = Object.assign(document.createElement("progress"), {max: 1, value: 0});
    bar.style.width = "100%";
    const cancel = Object.assign(document.createElement("button"), {type: "button", textContent: "Cancel"});
    dialog.append(heading, message, bar, cancel);
    document.body.append(dialog);
    dialog.showModal();
    let last = first;
    let stopped = false;
    const finish = () => { stopped = true; dialog.close(); dialog.remove(); resolve(last); };
    cancel.addEventListener("click", async () => {
      cancel.disabled = true;
      message.textContent = "Cancelling…";
      await fetch(`/api/v1/jobs/${first.id}/cancel`, {method: "POST"}).catch(() => undefined);
    });
    dialog.addEventListener("cancel", event => event.preventDefault());          // Esc must not hide a running job
    const tick = async () => {
      if (stopped) return;
      try {
        const response = await fetch(`/api/v1/jobs/${first.id}`);
        if (response.ok) last = await response.json() as Job;
      } catch { /* try again */ }
      message.textContent = last.status === "queued" ? "Waiting for a free worker…" : last.message;
      bar.value = last.progress;
      if (["completed", "failed", "cancelled"].includes(last.status)) finish();
      else setTimeout(tick, 400);
    };
    void tick();
  });
}

/** Choose a model file, convert it on the server and open the resulting document. */
export function importModel(openDocument: (id: string) => Promise<void>): void {
  const picker = Object.assign(document.createElement("input"), {type: "file", accept: IMPORT_TYPES});
  picker.addEventListener("change", async () => {
    const file = picker.files?.[0];
    if (!file) return;
    let scale = "1";
    const kind = /\.(obj|stl|dxf)$/i.exec(file.name)?.[1].toLowerCase() as "obj" | "stl" | "dxf" | undefined;
    if (kind) {
      const preset = prefs().importScale[kind];
      if (prefs().importAsk) {
        const answer = await askText("Import scale", "Multiply the file's units by (1 = metres, 0.001 = millimetres):", String(preset));
        if (answer === null) return;
        scale = answer.replace(",", ".");
      } else scale = String(preset);
    }
    const form = new FormData();
    form.append("file", file);
    form.append("scale", scale);
    const response = await fetch("/api/v1/jobs/import", {method: "POST", body: form});
    if (!response.ok) { notice("Import", (await responseApiError(response)).message); return; }
    const job = await follow(`Importing ${file.name}`, await response.json() as Job);
    if (job.status === "completed" && job.result?.document_id) await openDocument(job.result.document_id);
    else if (job.status === "failed") notice("Import failed", job.message);
  });
  picker.click();
}

/** Export the open revision: choose a format, wait for the job, then download. */
export async function exportRevision(record: {id: string; latest_revision: number; name: string} | undefined): Promise<void> {
  if (!record) { notice("Export", "Open a stored document first."); return; }
  const format = await askChoice("Export", "Format:", await availableExports());
  if (!format) return;
  const response = await fetch(`/api/v1/documents/${encodeURIComponent(record.id)}/revisions/${record.latest_revision}/exports`, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({format})});
  if (!response.ok) { notice("Export", (await responseApiError(response)).message); return; }
  const job = await follow(`Exporting ${record.name}`, await response.json() as Job);
  if (job.status === "completed") {
    const link = Object.assign(document.createElement("a"), {href: `/api/v1/jobs/${job.id}/artifact`, download: job.artifact ?? ""});
    document.body.append(link);
    link.click();
    link.remove();
  } else if (job.status === "failed") notice("Export failed", job.message);
}
