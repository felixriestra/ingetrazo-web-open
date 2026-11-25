/**
 * The online component library and the user's own face-me images.
 *
 * "More components…" opens a searchable grid of the models published at the
 * library's address (through the server, which keeps the downloads cached); picking
 * one hands a placement to the toolbar. "Face-me image…" reads a transparent PNG from
 * the viewer's disk and asks for its real height; the next click in the model stands
 * it there.
 */
import {notice, askText} from "./dialogs";
import {requestTool} from "./library";

interface OnlineModel {id: string; name: string; category: string; size_cm?: number[] | null; license: string; author: string}

/** The image waiting to be placed (set by "Face-me image…", read by the placement tool). */
export const faceMe = {image: "", name: "", height: 1.75};

export async function browseOnlineLibrary(): Promise<void> {
  let listing: {reachable: boolean; source: string; models: OnlineModel[]};
  try {
    const response = await fetch("/api/v1/library/online");
    if (!response.ok) throw new Error(String(response.status));
    listing = await response.json();
  } catch {
    notice("Component library", "The online library could not be reached from the server.");
    return;
  }
  if (!listing.reachable) {
    notice("Component library", `The online library is not reachable right now (${listing.source}). Components already downloaded stay available; try again when the server is online.`);
    return;
  }
  const dialog = document.createElement("dialog");
  dialog.className = "shortcut-dialog online-dialog";
  dialog.addEventListener("close", () => dialog.remove());
  const heading = Object.assign(document.createElement("h2"), {textContent: `Component library · ${listing.models.length} models`});
  const search = Object.assign(document.createElement("input"), {type: "search", placeholder: "Search by name or category…"});
  const grid = document.createElement("div");
  grid.className = "online-grid";
  const close = Object.assign(document.createElement("button"), {type: "button", textContent: "Close"});
  close.addEventListener("click", () => dialog.close());

  const render = () => {
    const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    grid.replaceChildren();
    let shown = 0;
    for (const model of listing.models) {
      const haystack = `${model.name} ${model.category}`.toLowerCase();
      if (!words.every(word => haystack.includes(word))) continue;
      if (++shown > 120) break;                       // a page of results, not the whole catalogue
      const card = document.createElement("button");
      card.type = "button";
      card.className = "online-card";
      const picture = Object.assign(document.createElement("img"), {
        loading: "lazy", alt: "", src: `/api/v1/library/online/${encodeURIComponent(model.id)}/thumb`});
      const label = Object.assign(document.createElement("span"), {textContent: model.name});
      card.title = [model.category, model.size_cm ? `${model.size_cm.join(" × ")} cm` : "",
        model.license ? `Licence: ${model.license}` : "", model.author ? `By ${model.author}` : ""].filter(Boolean).join(" · ");
      card.append(picture, label);
      card.addEventListener("click", () => { dialog.close(); requestTool(`place:online:${model.id}`); });
      grid.append(card);
    }
    if (!shown) grid.textContent = "No model matches.";
  };
  search.addEventListener("input", render);
  dialog.append(heading, search, grid, close);
  document.body.append(dialog);
  render();
  dialog.showModal();
  search.focus();
}

/** Choose an image, ask its real height, and start placing it. */
export function chooseFaceMeImage(): void {
  const picker = Object.assign(document.createElement("input"), {type: "file", accept: "image/png,image/webp,image/jpeg"});
  picker.addEventListener("change", async () => {
    const file = picker.files?.[0];
    if (!file) return;
    if (file.size > 8_000_000) { notice("Face-me image", "The image is larger than 8 MB."); return; }
    const answer = await askText("Face-me image", "Real height (m):", "1.75");
    if (answer === null) return;
    const height = Number(answer.replace(",", "."));
    if (!Number.isFinite(height) || height < 0.05 || height > 500) { notice("Face-me image", "The height must be between 0.05 and 500 metres."); return; }
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    Object.assign(faceMe, {image: btoa(binary), name: file.name, height});
    requestTool("place:faceme");
  });
  picker.click();
}
