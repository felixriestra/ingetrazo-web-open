/**
 * Parts section: the parts of the selected component, measured like a cut list.
 *
 * Mirrors the desktop's Parts tray: one row per part (name, size length × width ×
 * thickness, the material most of it wears), a check to show or hide each, a click to
 * select the part, "Split into Pieces", "Copy cut list", and the exploded view.
 */
import {askText, notice} from "./dialogs";

interface Part {id: string; name: string; material: string; size: number[]; surface: boolean; faces: number; hidden: boolean}
interface CutLine {qty: number; names: string[]; material: string; size: number[]; surface: boolean}
interface Listing {object_id: string; name: string; exploded: {factor: number; mode: string} | null; parts: Part[]; cut_list: CutLine[]}

export interface PartsDeps {
  record: () => {id: string; latest_revision: number} | undefined;
  selectedObjects: () => string[];
  editContext: () => string | undefined;
  unitFactor: () => number;
  unitLabel: () => string;
  command: (endpoint: string, body: Record<string, unknown>, message: string) => Promise<void>;
  selectObjects: (ids: string[]) => void;
}

export interface Parts {
  refresh: () => void;
}

export function mountParts(deps: PartsDeps): Parts {
  const panel = document.querySelector<HTMLElement>("#parts-panel")!;
  let container: string | undefined;
  let listing: Listing | undefined;
  let byMaterial = true;
  let sequence = 0;

  const note = Object.assign(document.createElement("p"), {className: "muted"});
  const allVisible = Object.assign(document.createElement("input"), {type: "checkbox"});
  const allLabel = document.createElement("label");
  allLabel.append(allVisible, " All parts visible");
  const table = document.createElement("table");
  table.className = "parts-table";
  const actions = document.createElement("div");
  actions.className = "tray-actions";
  const split = Object.assign(document.createElement("button"), {type: "button", textContent: "Split into Pieces", className: "secondary-button",
    title: "Regroup the component by the solids that do not touch"});
  const copy = Object.assign(document.createElement("button"), {type: "button", textContent: "Copy cut list", className: "secondary-button",
    title: "Copy the parts as a table that pastes into a spreadsheet"});
  actions.append(split, copy);
  const matchLabel = document.createElement("label");
  const matchBox = Object.assign(document.createElement("input"), {type: "checkbox", checked: true});
  matchLabel.append(matchBox, " Count identical parts only when the material matches too");

  const explode = document.createElement("div");
  explode.className = "parts-explode";
  const mode = document.createElement("select");
  for (const [value, label] of [["outward", "Outward"], ["z", "Along up"], ["x", "Along red"], ["y", "Along green"]]) mode.append(new Option(label, value));
  const slider = Object.assign(document.createElement("input"), {type: "range", min: "0", max: "300", step: "5", value: "0"});
  const percent = Object.assign(document.createElement("span"), {textContent: "0%"});
  const reassemble = Object.assign(document.createElement("button"), {type: "button", textContent: "Reassemble", className: "secondary-button"});
  explode.append(Object.assign(document.createElement("strong"), {textContent: "Exploded view"}), mode, slider, percent, reassemble);
  panel.append(note, allLabel, table, actions, matchLabel, explode);

  const length = (metres: number) => {
    const value = metres / deps.unitFactor();
    return `${value >= 100 ? value.toFixed(0) : value.toFixed(value >= 10 ? 1 : 2)}`;
  };
  const sizeText = (size: number[], surface: boolean) =>
    `${length(size[0])} × ${length(size[1])} × ${surface ? "surface" : length(size[2])} ${deps.unitLabel()}`;

  function render(): void {
    table.replaceChildren();
    const has = !!listing && listing.parts.length > 0;
    allLabel.hidden = actions.hidden = matchLabel.hidden = explode.hidden = !has;
    split.hidden = !listing;
    if (!listing) { note.textContent = "Select a component or group to see its parts."; return; }
    note.textContent = has
      ? `${listing.name}: ${listing.parts.length} part${listing.parts.length === 1 ? "" : "s"}`
      : `${listing.name} has no parts of its own. Split into Pieces regroups it by the solids that do not touch.`;
    const hiddenCount = listing.parts.filter(part => part.hidden).length;
    allVisible.checked = hiddenCount === 0;
    allVisible.indeterminate = hiddenCount > 0 && hiddenCount < listing.parts.length;
    const head = table.createTHead().insertRow();
    for (const title of ["", "Name", "Size", "Material"]) head.append(Object.assign(document.createElement("th"), {textContent: title}));
    const body = table.createTBody();
    for (const part of listing.parts) {
      const row = body.insertRow();
      row.className = part.hidden ? "part-hidden" : "";
      const check = Object.assign(document.createElement("input"), {type: "checkbox", checked: !part.hidden, title: part.hidden ? "Show" : "Hide"});
      check.addEventListener("change", () => void deps.command("parts-hide", {object_ids: [part.id], hidden: !check.checked}, check.checked ? "part shown" : "part hidden"));
      row.insertCell().append(check);
      const name = row.insertCell();
      name.textContent = part.name;
      name.title = "Click to select · double-click to rename";
      name.addEventListener("click", () => deps.selectObjects([part.id]));
      name.addEventListener("dblclick", async () => {
        const next = await askText("Rename part", "Name:", part.name);
        if (next && next !== part.name) void deps.command("object-lifecycle", {object_id: part.id, operation: "rename", name: next}, "part renamed");
      });
      row.insertCell().textContent = sizeText(part.size, part.surface);
      row.insertCell().textContent = part.material;
    }
    const exploded = listing.exploded;
    slider.value = String(exploded ? Math.round(exploded.factor * 100) : 0);
    percent.textContent = `${slider.value}%`;
    if (exploded) mode.value = exploded.mode;
  }

  async function load(): Promise<void> {
    const record = deps.record();
    const mine = ++sequence;
    if (!record || !container) { listing = undefined; render(); return; }
    try {
      const response = await fetch(`/api/v1/documents/${encodeURIComponent(record.id)}/revisions/${record.latest_revision}/parts?object_id=${encodeURIComponent(container)}&by_material=${byMaterial}`);
      if (mine !== sequence) return;
      listing = response.ok ? await response.json() as Listing : undefined;   // a face-me figure, or an object that is gone
    } catch { listing = undefined; }
    render();
  }

  function refresh(): void {
    const selected = deps.selectedObjects();
    // Selecting one of the listed parts keeps its component on show.
    if (selected.length === 1 && !(container && selected[0].startsWith(`${container}/`))) container = selected[0];
    else if (deps.editContext()) container = deps.editContext();
    void load();
  }

  const exploder = () => {
    if (!listing) return;
    void deps.command("explode-view", {object_id: listing.object_id, factor: Number(slider.value) / 100, mode: mode.value}, "exploded view set");
  };
  slider.addEventListener("input", () => { percent.textContent = `${slider.value}%`; });
  slider.addEventListener("change", exploder);
  mode.addEventListener("change", () => { if (listing?.exploded) exploder(); });
  reassemble.addEventListener("click", () => { slider.value = "0"; exploder(); });
  allVisible.addEventListener("change", () => {
    if (!listing) return;
    const hide = listing.parts.every(part => !part.hidden);
    const targets = listing.parts.filter(part => part.hidden === !hide).map(part => part.id);
    if (targets.length) void deps.command("parts-hide", {object_ids: targets, hidden: hide}, hide ? "parts hidden" : "parts shown");
  });
  split.addEventListener("click", () => {
    if (!listing) return;
    if (listing.object_id.includes("/")) { notice("Split into Pieces", "Leave the group you are editing and select the top-level component first."); return; }
    void deps.command("split-into-pieces", {object_id: listing.object_id}, "split into pieces");
  });
  matchBox.addEventListener("change", () => { byMaterial = matchBox.checked; void load(); });
  copy.addEventListener("click", async () => {
    if (!listing) return;
    const lines = ["Qty\tParts\tMaterial\tLength\tWidth\tThickness",
      ...listing.cut_list.map(line => [line.qty, line.names.join(", "), line.material, length(line.size[0]), length(line.size[1]),
        line.surface ? "surface" : length(line.size[2])].join("\t"))];
    try {
      await navigator.clipboard.writeText(`${lines.join("\n")}\n`);
      notice("Cut list copied", `${listing.cut_list.length} lines, ${listing.parts.length} parts (${deps.unitLabel()}).`);
    } catch {
      notice("Cut list", lines.join("\n"));
    }
  });

  document.addEventListener("ingetrazo:context", refresh);
  document.addEventListener("ingetrazo:loaded", () => void load());
  render();
  return {refresh};
}
