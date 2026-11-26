import "./auth";
import {onPrefsChange, prefs} from "./prefs";
import {mountChrome} from "./chrome";
import {mountGestures} from "./gestures";
import {mountLibrary} from "./library";
import {mountComponents} from "./components";
import {askText, confirmDialog, notice} from "./dialogs";
import {exportRevision} from "./convert";
import {parseApiError} from "./api";
import {signOut, whoAmI} from "./auth";
import {mountParts} from "./parts";
import {openComposer} from "./composer";
import {initLanguage} from "./i18n";
import {browseOnlineLibrary, chooseFaceMeImage} from "./online";
import {mountSelection} from "./selection";
import {mountToolForms} from "./toolforms";
import {mountTrays} from "./trays";
import "./styles.css";
import "./theme";
import {IngeTrazoViewer} from "./viewer";
import type {DocumentRecord, MeasurementInfo, OutlineItem, PickInfo, SavedViewDetail, SceneSummary, SectionPlaneDetail} from "./types";

const fileInput = document.querySelector<HTMLInputElement>("#file")!;
const viewport = document.querySelector<HTMLElement>("#viewport")!;
const empty = document.querySelector<HTMLElement>("#empty")!;
const status = document.querySelector<HTMLElement>("#status")!;
const summaryElement = document.querySelector<HTMLElement>("#summary")!;
const progress = document.querySelector<HTMLElement>("#progress")!;
const progressFill = progress.querySelector<HTMLElement>("span")!;
const projection = document.querySelector<HTMLButtonElement>("#projection")!;
const saveButton = document.querySelector<HTMLButtonElement>("#save")!;
const cancelButton = document.querySelector<HTMLButtonElement>("#cancel-operation")!;
const savePresentationButton = document.querySelector<HTMLButtonElement>("#save-presentation-revision")!;
const historyActions = document.querySelector<HTMLElement>("#history-actions")!;
const undoButton = document.querySelector<HTMLButtonElement>("#undo-revision")!;
const redoButton = document.querySelector<HTMLButtonElement>("#redo-revision")!;
const restoreForm = document.querySelector<HTMLFormElement>("#restore-revision")!;
const restoreSelect = restoreForm.querySelector<HTMLSelectElement>("select")!;
const createTools = document.querySelector<HTMLDetailsElement>("#create-tools")!;
const createBoxForm = document.querySelector<HTMLFormElement>("#create-box")!;
const createBoxButton = createBoxForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const createLineForm = document.querySelector<HTMLFormElement>("#create-line")!;
const createLineButton = createLineForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const createRectangleForm = document.querySelector<HTMLFormElement>("#create-rectangle")!;
const createRectangleButton = createRectangleForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const createCircleForm = document.querySelector<HTMLFormElement>("#create-circle")!;
const createCircleButton = createCircleForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const createArcForm = document.querySelector<HTMLFormElement>("#create-arc")!;
const createArcButton = createArcForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const createDimensionForm = document.querySelector<HTMLFormElement>("#create-dimension")!;
const createDimensionButton = createDimensionForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const createTextForm = document.querySelector<HTMLFormElement>("#create-text")!;
const createTextButton = createTextForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const createGuideForm = document.querySelector<HTMLFormElement>("#create-guide")!;
const createGuideButton = createGuideForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const documentsElement = document.querySelector<HTMLUListElement>("#documents")!;
const libraryEmpty = document.querySelector<HTMLElement>("#library-empty")!;
const layersElement = document.querySelector<HTMLUListElement>("#layers")!;
const outlinePanel = document.querySelector<HTMLElement>("#outline-panel")!;
const outlineElement = document.querySelector<HTMLUListElement>("#outline")!;
const outlineNote = document.querySelector<HTMLElement>("#outline-note")!;
const selectionPanel = document.querySelector<HTMLElement>("#selection-panel")!;
const selectionElement = document.querySelector<HTMLElement>("#selection")!;
const moveForm = document.querySelector<HTMLFormElement>("#move-object")!;
const moveButton = moveForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const rotateForm = document.querySelector<HTMLFormElement>("#rotate-object")!;
const rotateButton = rotateForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const scaleForm = document.querySelector<HTMLFormElement>("#scale-object")!;
const scaleButton = scaleForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const pushPullForm = document.querySelector<HTMLFormElement>("#push-pull-object")!;
const pushPullButton = pushPullForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const offsetForm = document.querySelector<HTMLFormElement>("#offset-face")!;
const offsetButton = offsetForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const materialForm = document.querySelector<HTMLFormElement>("#object-material")!;
const materialButton = materialForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const clearMaterialButton = document.querySelector<HTMLButtonElement>("#clear-object-material")!;
const ifcForm = document.querySelector<HTMLFormElement>("#object-ifc")!;
const ifcButton = ifcForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const clearIfcButton = document.querySelector<HTMLButtonElement>("#clear-object-ifc")!;
const bimPanel = document.querySelector<HTMLElement>("#bim-panel")!;
const bimObjects = document.querySelector<HTMLElement>("#bim-objects")!;
const quantitiesLink = document.querySelector<HTMLAnchorElement>("#export-quantities")!;
const ifcLink = document.querySelector<HTMLAnchorElement>("#export-ifc")!;
const geospatialPanel = document.querySelector<HTMLElement>("#geospatial-panel")!;
const georefSummary = document.querySelector<HTMLElement>("#georef-summary")!;
const georefForm = document.querySelector<HTMLFormElement>("#set-georef")!;
const georefButton = georefForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const mapForm = document.querySelector<HTMLFormElement>("#set-map")!;
const mapButton = mapForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const clearMapButton = document.querySelector<HTMLButtonElement>("#clear-map")!;
const terrainForm = document.querySelector<HTMLFormElement>("#import-terrain")!;
const terrainButton = terrainForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const surveyForm = document.querySelector<HTMLFormElement>("#import-survey")!;
const surveyButton = surveyForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const geopathForm = document.querySelector<HTMLFormElement>("#create-geopath")!;
const geopathButton = geopathForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const displayPanel = document.querySelector<HTMLElement>("#display-panel")!;
const styleForm = document.querySelector<HTMLFormElement>("#set-style")!;
const styleButton = styleForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const shadowForm = document.querySelector<HTMLFormElement>("#set-shadows")!;
const shadowButton = shadowForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const sunSummary = document.querySelector<HTMLElement>("#sun-summary")!;
const sheetsPanel = document.querySelector<HTMLElement>("#sheets-panel")!;
const sheetForm = document.querySelector<HTMLFormElement>("#create-sheet")!;
const sheetButton = sheetForm.querySelector<HTMLButtonElement>("button[type=submit]")!;
const sheetsElement = document.querySelector<HTMLElement>("#sheets")!;
const lifecycleControls = document.querySelector<HTMLElement>("#object-lifecycle")!;
const objectNameInput = document.querySelector<HTMLInputElement>("#object-name")!;
const renameButton = document.querySelector<HTMLButtonElement>("#rename-object")!;
const duplicateButton = document.querySelector<HTMLButtonElement>("#duplicate-object")!;
const copyButton = document.querySelector<HTMLButtonElement>("#copy-object")!;
const pasteButton = document.querySelector<HTMLButtonElement>("#paste-object")!;
const deleteButton = document.querySelector<HTMLButtonElement>("#delete-object")!;
const viewsPanel = document.querySelector<HTMLElement>("#views-panel")!;
const viewsElement = document.querySelector<HTMLElement>("#views")!;
const sectionsPanel = document.querySelector<HTMLElement>("#sections-panel")!;
const sectionsElement = document.querySelector<HTMLElement>("#sections")!;
const sectionCut = document.querySelector<HTMLInputElement>("#section-cut")!;
const sectionPlane = document.querySelector<HTMLInputElement>("#section-plane")!;
const measureButton = document.querySelector<HTMLButtonElement>("#measure")!;
const sketchLineButton = document.querySelector<HTMLButtonElement>("#sketch-line")!;
const measurementPanel = document.querySelector<HTMLElement>("#measurement-panel")!;
const measurementElement = document.querySelector<HTMLElement>("#measurement")!;
const viewer = new IngeTrazoViewer(document.querySelector<HTMLCanvasElement>("#viewer")!);
// Test hook: ?debug exposes the viewer to the console / browser automation.
if (location.search.includes("debug")) (window as unknown as {ingetrazoViewer: unknown}).ingetrazoViewer = viewer;
const trays = mountTrays();
const library = mountLibrary({
  applyRevision: async (revised, message) => {
    const record = revised as DocumentRecord;
    await refreshLibrary();
    await loadStored(record);
    status.textContent = `${record.name} · revision ${record.latest_revision} · ${message}`;
  },
  setStatus: text => { status.textContent = text; },
});
const selection = mountSelection(viewer);
viewer.nameOf = id => outlineIndex.get(id)?.name;
const components = mountComponents(ids => selection.setObjects(ids));
const unitFactor = () => currentUnits.length === "mm" ? 0.001
  : currentUnits.length === "cm" ? 0.01
    : currentUnits.length === "ft" ? 0.3048
      : currentUnits.length === "in" ? 0.0254 : 1;
const toolForms = mountToolForms({
  record: () => currentRecord,
  selectedObject: () => selectedObjectId,
  describeObject: id => outlineIndex.get(id)?.name ?? id,
  unitFactor,
  unitLabel: () => currentUnits.length,
  presentationDirty: () => !savePresentationButton.disabled,
  applyRevision: async (revised, message) => {
    const record = revised as DocumentRecord;
    await refreshLibrary();
    await loadStored(record);
    status.textContent = `${record.name} · revision ${record.latest_revision} · ${message}`;
  },
  setStatus: text => { status.textContent = text; },
  layerNames: () => [...layerControls.keys()],
  camera: () => viewer.cameraState(),
});
if (location.search.includes("debug")) (window as unknown as {ingetrazoForms: unknown}).ingetrazoForms = toolForms;
const vcb = document.querySelector<HTMLInputElement>("#vcb")!;
const gestures = mountGestures({
  viewer,
  record: () => currentRecord,
  selectedObject: () => selection.objects()[0] ?? selectedObjectId,
  selectedObjects: () => selection.objects(),
  selectedFaces: () => selection.faces(),
  selectedEdges: () => selection.edges(),
  selectFaces: faces => selection.setFaces(faces),
  unitFactor,
  unitLabel: () => currentUnits.length,
  unitPrecision: () => currentUnits.precision,
  presentationDirty: () => !savePresentationButton.disabled,
  applyRevision: async (revised, message) => {
    const record = revised as DocumentRecord;
    await refreshLibrary();
    await loadStored(record);
    status.textContent = `${record.name} · revision ${record.latest_revision} · ${message}`;
  },
  setStatus: text => { status.textContent = text; },
  setHint: text => { document.querySelector<HTMLElement>("#tool-hint")!.textContent = text; },
  setVcb: text => { vcb.value = text; },
  ask: (label, initial) => new Promise(resolve => {
    const dialog = document.createElement("dialog");
    dialog.className = "shortcut-dialog";
    const form = document.createElement("form");
    form.method = "dialog";
    const caption = document.createElement("label");
    caption.textContent = label;
    const input = document.createElement("input");
    input.type = "text";
    input.value = initial;
    input.maxLength = 4000;
    caption.append(input);
    const ok = Object.assign(document.createElement("button"), {type: "submit", textContent: "OK"});
    const cancel = Object.assign(document.createElement("button"), {type: "button", textContent: "Cancel"});
    form.append(caption, ok, cancel);
    dialog.append(form);
    document.body.append(dialog);
    let answer: string | null = null;
    form.addEventListener("submit", () => { answer = input.value.trim() || null; });
    cancel.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => { dialog.remove(); resolve(answer); });
    dialog.showModal();
    input.focus();
  }),
  paintSettings: () => {
    const hex = document.querySelector<HTMLInputElement>("#object-material input[name=color]")?.value ?? "#d8cbb0";
    const opacity = Number(document.querySelector<HTMLInputElement>("#object-material input[name=opacity]")?.value ?? 1);
    const channel = (offset: number) => parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return {color: [channel(1), channel(3), channel(5)] as [number, number, number], opacity: Number.isFinite(opacity) ? opacity : 1, texture: library.activeTexture(), material: library.activeMaterial()};
  },
});
const parts = mountParts({
  record: () => currentRecord,
  selectedObjects: () => selection.objects(),
  editContext: () => viewer.getEditContext(),
  unitFactor,
  unitLabel: () => currentUnits.length,
  command: revisionCommand,
  selectObjects: ids => selection.setObjects(ids),
});
selection.onChange(() => { if (selection.objects().length === 1) parts.refresh(); });
trays.addActions("components", [
  {label: "More components…", run: () => void browseOnlineLibrary()},
  {label: "Face-me image…", run: chooseFaceMeImage},
]);
trays.addActions("layers", [{label: "New layer…", run: () => toolForms.show("layer_new")}]);
trays.addActions("scenes", [
  {label: "Add scene…", run: () => toolForms.show("scene_add")},
  {label: "Delete scene…", run: () => toolForms.show("scene_delete")},
]);
trays.addActions("entity", [{label: "Move to layer…", run: () => toolForms.show("layer_assign")}]);
mountChrome(viewer, toolForms, gestures, selection);
let previewUrl: string | undefined;
let currentFile: File | undefined;
let currentRecord: DocumentRecord | undefined;
let loadedDocumentId: string | undefined;
let activeUpload: XMLHttpRequest | undefined;
let activeFetch: AbortController | undefined;
let openSequence = 0;
let selectedObjectId: string | undefined;
let clipboardObjectId: string | undefined;
const outlineIndex = new Map<string, OutlineItem>();
const layerControls = new Map<string, {
  input: HTMLInputElement;
  state: HTMLSpanElement;
  locked: boolean;
}>();
const objectControls = new Map<string, {
  button: HTMLButtonElement;
  hidden: boolean;
  item: OutlineItem;
}>();
let sectionPlanes: SectionPlaneDetail[] = [];
let selectedSection: SectionPlaneDetail | undefined;
let autoSaveTimer: number | undefined;      // see scheduleAutoSave
let documentUnits = {length: "m", precision: 2};
let currentUnits = documentUnits;
/** The units in force: the document's own, or the fixed ones chosen in Preferences > Units. */
function refreshUnits(): void {
  const p = prefs();
  currentUnits = p.unitsMode === "fixed" ? {length: p.unitLength, precision: p.unitPrecision} : documentUnits;
}
let sketchLineStart: [number, number, number] | undefined;
const baselineLayerVisibility = new Map<string, boolean>();
const baselineObjectHidden = new Map<string, boolean>();

function addSummary(label: string, value: string): void {
  const term = document.createElement("dt");
  const detail = document.createElement("dd");
  term.textContent = label;
  detail.textContent = value;
  summaryElement.append(term, detail);
}

function configureRevisionRestore(record?: DocumentRecord): void {
  restoreSelect.replaceChildren();
  restoreForm.hidden = !record || record.revisions.length < 2;
  createTools.hidden = !record;
  historyActions.hidden = !record;
  undoButton.disabled = !record || !record.undo?.undo_to;
  redoButton.disabled = !record || !record.undo?.redo_to;
  undoButton.title = record?.undo?.undo_to ? `Undo (back to revision ${record.undo.undo_to})` : "Nothing to undo";
  redoButton.title = record?.undo?.redo_to ? `Redo (forward to revision ${record.undo.redo_to})` : "Nothing to redo";
  if (!record) return;
  for (const revision of [...record.revisions].reverse()) {
    if (revision.number === record.latest_revision) continue;
    const option = document.createElement("option");
    option.value = String(revision.number);
    option.textContent = `Revision ${revision.number} · ${new Date(revision.created_at).toLocaleString()}`;
    restoreSelect.append(option);
  }
}

function renderSummary(data: SceneSummary): void {
  for (const button of [
    createBoxButton, createLineButton, createRectangleButton, createCircleButton,
    createArcButton, createDimensionButton, createTextButton, createGuideButton,
  ]) button.disabled = false;
  documentUnits = data.units;
  refreshUnits();
  summaryElement.replaceChildren();
  addSummary("Faces", data.unique_geometry.faces.toLocaleString());
  addSummary("Edges", data.unique_geometry.edges.toLocaleString());
  addSummary("Placements", data.placements.toLocaleString());
  addSummary("Layers", data.layers.toLocaleString());
  addSummary("Materials", data.materials.toLocaleString());
  if (data.dimensions) addSummary("Dimensions", data.dimensions.toLocaleString());
  if (data.text_labels) addSummary("Text labels", data.text_labels.toLocaleString());
  if (data.guides) addSummary("Guides", data.guides.toLocaleString());
  if (data.reference_images) addSummary("Reference images", data.reference_images.toLocaleString());
  addSummary("Units", data.units.length);
  if (data.bounds.min && data.bounds.max) {
    const size = data.bounds.max.map((value, index) => value - data.bounds.min![index]);
    addSummary("Size", size.map(value => value.toFixed(3)).join(" × "));
  }
  layersElement.replaceChildren();
  layerControls.clear();
  baselineLayerVisibility.clear();
  for (const layer of data.layer_details ?? []) {
    const item = document.createElement("li");
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    const name = document.createElement("span");
    const state = document.createElement("span");
    checkbox.type = "checkbox";
    checkbox.checked = layer.visible;
    checkbox.addEventListener("change", () => {
      setLayerVisibility(layer.name, checkbox.checked);
    });
    name.textContent = layer.name;
    state.textContent = layer.locked ? "Locked" : layer.visible ? "Visible" : "Hidden";
    state.className = layer.visible ? "state-visible" : "state-hidden";
    label.append(checkbox, name);
    const tools = document.createElement("span");
    tools.className = "layer-tools";
    const lock = Object.assign(document.createElement("button"), {
      type: "button", textContent: layer.locked ? "Unlock" : "Lock", className: "layer-button",
      title: layer.locked ? "Unlock this layer" : "Lock this layer: its objects cannot be selected or edited"});
    lock.addEventListener("click", () => void revisionCommand(
      "set-layer-lock", {name: layer.name, locked: !layer.locked}, layer.locked ? "layer unlocked" : "layer locked"));
    tools.append(state, lock);
    if (layer.name !== "Layer 0") {          // the default layer is permanent
      const rename = Object.assign(document.createElement("button"), {
        type: "button", textContent: "Rename", className: "layer-button", title: "Rename this layer"});
      rename.addEventListener("click", async () => {
        const next = await askText("Rename layer", "Name:", layer.name);
        if (next && next !== layer.name) void revisionCommand("rename-layer", {name: layer.name, new_name: next}, "layer renamed");
      });
      const remove = Object.assign(document.createElement("button"), {
        type: "button", textContent: "✕", className: "layer-button", title: "Delete this layer; its contents move to Layer 0"});
      remove.addEventListener("click", async () => {
        if (await confirmDialog("Delete layer", `Delete «${layer.name}»?\n\nIts contents are not deleted: they move to Layer 0.`)) {
          void revisionCommand("delete-layer", {name: layer.name}, "layer deleted");
        }
      });
      tools.append(rename, remove);
    }
    item.append(label, tools);
    layersElement.append(item);
    layerControls.set(layer.name, {input: checkbox, state, locked: layer.locked});
    baselineLayerVisibility.set(layer.name, layer.visible);
  }
  updatePresentationRevisionState();
  renderSavedViews(data.saved_view_details ?? []);
  renderSections(
    data.section_details ?? [],
    data.section_cuts_visible ?? true,
    data.section_planes_visible ?? true,
  );
  renderOutline(data.outline?.items ?? [], data.outline?.truncated ?? false);
  renderBim(data.bim_objects ?? []);
  viewer.setAnnotations(
    data.dimension_details ?? [], data.text_label_details ?? [], data.guide_details ?? [],
  );
  viewer.setGeospatial(data.survey_point_details ?? [], data.geo_path_details ?? []);
  viewer.setMap(data.map);
  viewer.setReferenceMesh(data.photogrammetry);
  renderGeospatial(data);
  renderDisplay(data);
  renderSheets(data);
}

function renderSheets(data: SceneSummary): void {
  sheetsPanel.hidden = currentRecord === undefined;
  sheetsElement.replaceChildren();
  const viewSelect = sheetForm.querySelector<HTMLSelectElement>("select[name=view]")!;
  for (const option of [...viewSelect.querySelectorAll("option[data-saved]")]) option.remove();
  for (const view of data.saved_view_details ?? []) {
    const option = document.createElement("option");
    option.value = `scene:${view.name}`;
    option.textContent = `Scene · ${view.name}`;
    option.dataset.saved = "true";
    viewSelect.append(option);
  }
  for (const sheet of data.composition_details ?? []) {
    const row = document.createElement("div");
    row.className = "bim-object";
    const title = document.createElement("strong");
    title.textContent = sheet.name;
    const detail = document.createElement("span");
    detail.textContent = `${sheet.paper} ${sheet.landscape ? "landscape" : "portrait"} · ${sheet.frames} frame${sheet.frames === 1 ? "" : "s"}`;
    const link = document.createElement("a");
    link.className = "secondary-button";
    link.textContent = "Export PDF";
    link.download = "";
    if (currentRecord) link.href = `/api/v1/documents/${encodeURIComponent(currentRecord.id)}/revisions/${currentRecord.latest_revision}/sheets/${sheet.index}.pdf`;
    const compose = Object.assign(document.createElement("button"), {type: "button", className: "secondary-button", textContent: "Open composer"});
    compose.addEventListener("click", () => void openComposer({
      record: () => currentRecord,
      revisionMade: async revised => {
        const record = revised as DocumentRecord;
        await refreshLibrary();
        await loadStored(record);
      },
    }, sheet.index));
    row.append(title, detail, compose, link);
    sheetsElement.append(row);
  }
}

function renderDisplay(data: SceneSummary): void {
  displayPanel.hidden = currentRecord === undefined;
  if (data.display_style) {
    styleForm.querySelector<HTMLSelectElement>("select[name=name]")!.value = data.display_style.name;
    viewer.applyStyle(data.display_style);
  }
  const shadows = data.shadows;
  if (!shadows) return;
  shadowForm.querySelector<HTMLInputElement>("input[name=enabled]")!.checked = shadows.enabled;
  for (const field of ["month", "day", "hour", "minute", "darkness"] as const) {
    shadowForm.querySelector<HTMLInputElement>(`input[name=${field}]`)!.value = String(shadows[field]);
  }
  shadowForm.querySelector<HTMLInputElement>("input[name=utc_offset]")!.value =
    shadows.utc_offset === undefined ? "" : String(shadows.utc_offset);
  viewer.setSun(data.sun, shadows.enabled, shadows.darkness);
  if (!shadows.enabled) {
    sunSummary.textContent = "Solar shadows are off.";
  } else if (!data.sun?.direction) {
    sunSummary.textContent = "The sun is below the horizon at this date and time.";
  } else {
    sunSummary.textContent = `Sun elevation ${data.sun.elevation.toFixed(1)}° · azimuth ${data.sun.azimuth.toFixed(1)}°`;
  }
}

function renderGeospatial(data: SceneSummary): void {
  geospatialPanel.hidden = currentRecord === undefined;
  const datum = data.georef_detail;
  if (datum) {
    georefSummary.textContent = `${datum.lat.toFixed(6)}, ${datum.lon.toFixed(6)} · UTM ${datum.zone}${datum.hemisphere} · ${data.survey_points ?? 0} survey points · ${data.geo_paths ?? 0} paths`;
    georefForm.querySelector<HTMLInputElement>("input[name=latitude]")!.value = String(datum.lat);
    georefForm.querySelector<HTMLInputElement>("input[name=longitude]")!.value = String(datum.lon);
    georefForm.querySelector<HTMLInputElement>("input[name=altitude]")!.value = String(datum.alt);
    georefForm.querySelector<HTMLInputElement>("input[name=north]")!.value = String(datum.north ?? 0);
    surveyForm.querySelector<HTMLInputElement>("input[name=zone]")!.value = String(datum.zone);
    surveyForm.querySelector<HTMLSelectElement>("select[name=hemisphere]")!.value = datum.hemisphere;
  } else {
    georefSummary.textContent = "No geographic datum yet.";
  }
  if (data.photogrammetry) {
    georefSummary.textContent += ` · photogrammetry ${data.photogrammetry.triangles.toLocaleString()} triangles`;
  }
  if (data.map) {
    georefSummary.textContent += ` · ${data.map.name}, z${data.map.zoom}, ${data.map.tiles.length} tiles`;
    mapForm.querySelector<HTMLSelectElement>("select[name=source]")!.value = data.map.source;
    mapForm.querySelector<HTMLInputElement>("input[name=zoom]")!.value = String(data.map.zoom);
    mapForm.querySelector<HTMLInputElement>("input[name=radius]")!.value = String(data.map.radius);
    mapForm.querySelector<HTMLInputElement>("input[name=opacity]")!.value = String(data.map.opacity);
  }
}

function renderBim(objects: NonNullable<SceneSummary["bim_objects"]>): void {
  bimObjects.replaceChildren();
  bimPanel.hidden = objects.length === 0;
  for (const object of objects) {
    const row = document.createElement("div");
    const title = document.createElement("strong");
    const quantity = document.createElement("span");
    const raw = document.createElement("span");
    row.className = "bim-object";
    title.textContent = `${object.class.replace(/^Ifc/, "")} · ${object.name}`;
    const unit = object.takeoff_unit === "m2" ? "m²"
      : object.takeoff_unit === "m3" ? "m³" : object.takeoff_unit;
    const takeoff = document.createElement("b");
    takeoff.textContent = `${object.takeoff === null ? "—" : object.takeoff.toFixed(unit === "und" ? 0 : 3)} ${unit}`;
    quantity.append("Takeoff: ", takeoff);
    raw.textContent = `Area ${object.area_m2.toFixed(3)} m² · Volume ${object.volume_m3 === null ? "—" : `${object.volume_m3.toFixed(3)} m³`}`;
    row.append(title, quantity, raw);
    bimObjects.append(row);
  }
  const revision = currentRecord?.latest_revision;
  if (currentRecord && revision) {
    const prefix = `/api/v1/documents/${encodeURIComponent(currentRecord.id)}/revisions/${revision}`;
    quantitiesLink.href = `${prefix}/quantities.csv`;
    ifcLink.href = `${prefix}/model.ifc`;
    quantitiesLink.hidden = false;
    ifcLink.hidden = false;
  } else {
    quantitiesLink.hidden = true;
    ifcLink.hidden = true;
  }
}

function formatLength(metres: number): string {
  const precision = Math.max(0, Math.min(6, currentUnits.precision));
  const factor = currentUnits.length === "mm" ? 1000 : currentUnits.length === "cm" ? 100 : 1;
  if (["m", "cm", "mm"].includes(currentUnits.length)) {
    return `${(metres * factor).toFixed(precision)} ${currentUnits.length}`;
  }
  const imperialFactor = currentUnits.length === "ft" ? 1 / 0.3048 : 1 / 0.0254;
  const suffix = currentUnits.length === "ft" ? "′" : "″";
  return `${(metres * imperialFactor).toFixed(precision)}${suffix}`;
}

function renderMeasurement(measurement: MeasurementInfo | null): void {
  measurementPanel.hidden = measurement === null;
  if (!measurement) {
    measurementElement.textContent = "";
    vcb.value = "";
    measureButton.classList.remove("active");
    measureButton.textContent = "Measure";
    return;
  }
  if (!measurement.complete || measurement.distance === null) {
    measurementElement.textContent = "Choose the second point…";
    vcb.value = "…";
    status.textContent = "Choose the second measurement point.";
    return;
  }
  measurementElement.textContent = formatLength(measurement.distance);
  vcb.value = formatLength(measurement.distance);
  status.textContent = `Measured ${formatLength(measurement.distance)}.`;
  measureButton.classList.remove("active");
  measureButton.textContent = "Measure";
}

function setLayerVisibility(name: string, visible: boolean): void {
  const control = layerControls.get(name);
  if (control) {
    control.input.checked = visible;
    control.state.textContent = control.locked ? "Locked" : visible ? "Visible" : "Hidden";
    control.state.className = visible ? "state-visible" : "state-hidden";
  }
  viewer.setLayerVisible(name, visible);
  updatePresentationRevisionState();
}

function updatePresentationRevisionState(): void {
  const layersChanged = [...layerControls.entries()].some(
    ([name, control]) => control.input.checked !== baselineLayerVisibility.get(name),
  );
  const objectsChanged = [...objectControls.entries()].some(
    ([nativeId, control]) => control.hidden !== baselineObjectHidden.get(nativeId),
  );
  savePresentationButton.hidden = currentRecord === undefined;
  savePresentationButton.disabled = currentRecord === undefined || (!layersChanged && !objectsChanged);
  moveButton.disabled = currentRecord === undefined || layersChanged || objectsChanged;
  rotateButton.disabled = moveButton.disabled;
  scaleButton.disabled = moveButton.disabled;
  pushPullButton.disabled = moveButton.disabled;
  offsetButton.disabled = moveButton.disabled;
  materialButton.disabled = moveButton.disabled;
  clearMaterialButton.disabled = moveButton.disabled;
  ifcButton.disabled = moveButton.disabled;
  clearIfcButton.disabled = moveButton.disabled;
  duplicateButton.disabled = moveButton.disabled;
  copyButton.disabled = moveButton.disabled;
  pasteButton.disabled = moveButton.disabled || clipboardObjectId === undefined;
  deleteButton.disabled = moveButton.disabled;
  renameButton.disabled = moveButton.disabled;
  createBoxButton.disabled = moveButton.disabled;
  createLineButton.disabled = moveButton.disabled;
  createRectangleButton.disabled = moveButton.disabled;
  createCircleButton.disabled = moveButton.disabled;
  createArcButton.disabled = moveButton.disabled;
  createDimensionButton.disabled = moveButton.disabled;
  createTextButton.disabled = moveButton.disabled;
  createGuideButton.disabled = moveButton.disabled;
  georefButton.disabled = moveButton.disabled;
  surveyButton.disabled = moveButton.disabled;
  geopathButton.disabled = moveButton.disabled;
  mapButton.disabled = moveButton.disabled;
  clearMapButton.disabled = moveButton.disabled;
  terrainButton.disabled = moveButton.disabled;
  styleButton.disabled = moveButton.disabled;
  shadowButton.disabled = moveButton.disabled;
  sheetButton.disabled = moveButton.disabled;
  scheduleAutoSave();
}

/** Auto-save of presentation changes (Preferences > General): wait for a quiet spell, then press Save. */
function scheduleAutoSave(): void {
  if (autoSaveTimer !== undefined) { window.clearTimeout(autoSaveTimer); autoSaveTimer = undefined; }
  const p = prefs();
  if (!p.autoSavePresentation || savePresentationButton.hidden || savePresentationButton.disabled) return;
  autoSaveTimer = window.setTimeout(() => {
    autoSaveTimer = undefined;
    if (!savePresentationButton.disabled) { status.textContent = "Auto-saving presentation changes…"; savePresentationButton.click(); }
  }, p.autoSaveSeconds * 1000);
}
onPrefsChange(scheduleAutoSave);

function updateObjectControl(nativeId: string, hidden: boolean): void {
  const control = objectControls.get(nativeId);
  if (!control) return;
  control.hidden = hidden;
  control.item.hidden = hidden;
  control.item.visible = !hidden;
  control.button.textContent = hidden ? "○" : "●";
  control.button.classList.toggle("is-hidden", hidden);
  control.button.title = `${hidden ? "Show" : "Hide"} ${control.item.name}`;
  control.button.setAttribute("aria-label", control.button.title);
}

function setObjectHidden(nativeId: string, hidden: boolean): void {
  updateObjectControl(nativeId, hidden);
  viewer.setObjectHidden(nativeId, hidden);
  updatePresentationRevisionState();
}

function setHiddenObjects(nativeIds: Set<string>): void {
  for (const nativeId of objectControls.keys()) {
    updateObjectControl(nativeId, nativeIds.has(nativeId));
  }
  viewer.setHiddenObjects(nativeIds);
  updatePresentationRevisionState();
}

function applySavedView(view: SavedViewDetail): void {
  const projectionName = viewer.applyCamera(view);
  if (projectionName) projection.textContent = projectionName;
  const hidden = new Set(view.hidden_layers);
  for (const name of layerControls.keys()) setLayerVisibility(name, !hidden.has(name));
  if (view.hidden_objects !== undefined && view.hidden_objects !== null) {
    setHiddenObjects(new Set(
      view.hidden_object_visibility_ids ?? view.hidden_objects,
    ));
  }
  if (view.section) {
    selectedSection = sectionPlanes.find(plane => plane.id === view.section!.active);
    sectionCut.checked = Boolean(selectedSection) && (view.section.cuts_shown ?? true);
    sectionPlane.checked = Boolean(selectedSection) && (view.section.planes_shown ?? true);
    applySectionState();
    updateSectionButtons();
  }
  status.textContent = `Scene: ${view.name}`;
}

function applySectionState(): void {
  viewer.setSectionPlane(sectionCut.checked ? selectedSection ?? null : null);
  viewer.showSectionPlane(sectionPlane.checked ? selectedSection ?? null : null);
}

function updateSectionButtons(): void {
  sectionsElement.querySelectorAll<HTMLButtonElement>("button").forEach(button => {
    button.classList.toggle("active", Number(button.dataset.sectionId) === selectedSection?.id);
  });
}

function renderSections(planes: SectionPlaneDetail[], cutsVisible: boolean, planesVisible: boolean): void {
  sectionPlanes = planes;
  selectedSection = planes.find(plane => plane.active) ?? planes[0];
  sectionsElement.replaceChildren();
  sectionsPanel.hidden = planes.length === 0;
  sectionCut.checked = cutsVisible && Boolean(planes.find(plane => plane.active));
  sectionPlane.checked = planesVisible && Boolean(selectedSection);
  for (const plane of planes) {
    const button = document.createElement("button");
    const detail = document.createElement("span");
    button.type = "button";
    button.dataset.sectionId = String(plane.id);
    button.textContent = plane.symbol ? `${plane.symbol} — ${plane.name}` : plane.name;
    detail.textContent = `normal ${plane.normal.map(value => value.toFixed(2)).join(", ")}`;
    button.append(detail);
    button.addEventListener("click", () => {
      selectedSection = plane;
      sectionCut.checked = true;
      applySectionState();
      updateSectionButtons();
    });
    sectionsElement.append(button);
  }
  updateSectionButtons();
  applySectionState();
}

function renderSavedViews(views: SavedViewDetail[]): void {
  viewsElement.replaceChildren();
  viewsPanel.hidden = views.length === 0;
  for (const view of views) {
    const button = document.createElement("button");
    const name = document.createElement("strong");
    const detail = document.createElement("span");
    name.textContent = view.name;
    detail.textContent = view.perspective ? "Perspective" : "Parallel";
    button.append(name, detail);
    button.addEventListener("click", () => applySavedView(view));
    viewsElement.append(button);
  }
}

function outlineItem(item: OutlineItem, depth = 0): HTMLLIElement {
  outlineIndex.set(item.id, item);
  const row = document.createElement("li");
  row.dataset.objectId = item.id;
  const details = document.createElement("details");
  const heading = document.createElement("summary");
  const name = document.createElement("strong");
  const meta = document.createElement("span");
  name.textContent = item.name;
  meta.textContent = `${item.kind} · ${item.layer} · ${item.geometry.faces.toLocaleString()} faces`;
  heading.append(name, meta);
  details.append(heading);
  if (item.ifc?.class || item.ifc?.name) {
    const bim = document.createElement("p");
    bim.textContent = [item.ifc.class, item.ifc.name].filter(Boolean).join(" · ");
    details.append(bim);
  }
  if (item.children.length) {
    const children = document.createElement("ul");
    for (const child of item.children) children.append(outlineItem(child, depth + 1));
    details.append(children);
  }
  const focus = document.createElement("button");
  focus.type = "button";
  focus.className = "focus-object";
  focus.textContent = "◎";
  focus.title = `Select ${item.name} in the model`;
  focus.setAttribute("aria-label", `Select ${item.name} in the model`);
  focus.addEventListener("click", () => {
    if (viewer.selectObject(item.preview_id ?? item.id)) {
      renderSelection({
        objectId: item.id,
        object: item.name,
        kind: item.kind,
        layer: item.layer,
      });
    }
  });
  const actions = document.createElement("div");
  actions.className = "outline-actions";
  actions.append(focus);
  const visibilityId = item.visibility_id ?? item.native_id;
  if (depth === 0 && visibilityId) {
    const visibility = document.createElement("button");
    visibility.type = "button";
    visibility.className = "visibility-object";
    visibility.addEventListener("click", () => {
      const control = objectControls.get(visibilityId);
      if (control) setObjectHidden(visibilityId, !control.hidden);
    });
    actions.prepend(visibility);
    objectControls.set(visibilityId, {button: visibility, hidden: item.hidden, item});
    baselineObjectHidden.set(visibilityId, item.hidden);
    updateObjectControl(visibilityId, item.hidden);
  }
  row.append(details, actions);
  return row;
}

function renderOutline(items: OutlineItem[], truncated: boolean): void {
  outlineIndex.clear();
  objectControls.clear();
  baselineObjectHidden.clear();
  outlineElement.replaceChildren();
  outlinePanel.hidden = items.length === 0;
  outlineNote.hidden = !truncated;
  outlineNote.textContent = truncated ? "Only the first 500 objects are shown." : "";
  for (const item of items) outlineElement.append(outlineItem(item));
  updatePresentationRevisionState();
  components.setInModel(items.map(item => ({id: item.id, name: item.name, kind: item.kind})));
}

function rgbToHex(color: number[]): string {
  const channel = (value: number) => Math.round(
    Math.max(0, Math.min(1, Number(value) || 0)) * 255,
  ).toString(16).padStart(2, "0");
  return `#${channel(color[0])}${channel(color[1])}${channel(color[2])}`;
}

function renderSelection(selection: PickInfo | null): void {
  selectionElement.replaceChildren();
  selectedObjectId = undefined;
  moveForm.hidden = true;
  rotateForm.hidden = true;
  scaleForm.hidden = true;
  pushPullForm.hidden = true;
  offsetForm.hidden = true;
  materialForm.hidden = true;
  ifcForm.hidden = true;
  lifecycleControls.hidden = true;
  outlineElement.querySelectorAll(".selected-object").forEach(
    element => element.classList.remove("selected-object"),
  );
  selectionPanel.hidden = selection === null;
  if (!selection) return;
  const native = selection.objectId ? outlineIndex.get(selection.objectId) : undefined;
  const objectColor = native?.material?.color;
  const fields: Array<[string, string]> = [
    ["Object", native?.name ?? selection.object],
    ...(native?.kind || selection.kind
      ? [["Type", native?.kind ?? selection.kind!] as [string, string]] : []),
    ...(native?.layer || selection.layer
      ? [["Layer", native?.layer ?? selection.layer!] as [string, string]] : []),
    ...(selection.material ? [["Material", selection.material] as [string, string]] : []),
    ...(selection.triangle !== undefined
      ? [["Triangle", selection.triangle.toLocaleString()] as [string, string]] : []),
    ...(selection.point
      ? [["Point", selection.point.map(value => value.toFixed(3)).join(", ")] as [string, string]] : []),
    ...(objectColor?.length === 3
      ? [["Object colour", rgbToHex(objectColor)] as [string, string]] : []),
  ];
  for (const [label, value] of fields) {
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    selectionElement.append(term, detail);
  }
  if (selection.objectId && objectControls.has(selection.objectId) && currentRecord) {
    selectedObjectId = selection.objectId;
    moveForm.hidden = false;
    rotateForm.hidden = false;
    scaleForm.hidden = false;
    pushPullForm.hidden = !native || native.geometry.faces === 0;
    offsetForm.hidden = !native || native.geometry.faces !== 1;
    materialForm.hidden = !native || native.geometry.faces === 0;
    ifcForm.hidden = !native || native.geometry.faces === 0;
    lifecycleControls.hidden = false;
    objectNameInput.value = native?.name ?? selection.object;
    moveForm.querySelectorAll<HTMLInputElement>("input").forEach(input => {
      input.value = "0";
    });
    rotateForm.querySelector<HTMLInputElement>("input[name=degrees]")!.value = "0";
    scaleForm.querySelectorAll<HTMLInputElement>("input").forEach(input => {
      input.value = "1";
    });
    pushPullForm.querySelector<HTMLInputElement>("input[name=distance]")!.value = "0";
    pushPullForm.querySelector<HTMLInputElement>("input[name=keep_base]")!.checked = false;
    pushPullForm.querySelector<HTMLSelectElement>("select[name=direction]")!.value =
      native?.geometry.faces === 1 ? "normal" : "+z";
    offsetForm.querySelector<HTMLInputElement>("input[name=distance]")!.value = "0";
    materialForm.querySelector<HTMLInputElement>("input[name=color]")!.value =
      rgbToHex(objectColor?.length === 3 ? objectColor : [0.847, 0.796, 0.69]);
    materialForm.querySelector<HTMLInputElement>("input[name=opacity]")!.value =
      String(native?.material?.opacity ?? 1);
    ifcForm.querySelector<HTMLSelectElement>("select[name=class]")!.value =
      native?.ifc?.class ?? "IfcWall";
    ifcForm.querySelector<HTMLInputElement>("input[name=name]")!.value =
      native?.ifc?.name ?? native?.name ?? selection.object;
    updatePresentationRevisionState();
  }
  if (selection.objectId) {
    const match = [...outlineElement.querySelectorAll<HTMLElement>("[data-object-id]")]
      .find(element => element.dataset.objectId === selection.objectId);
    if (match) {
      match.classList.add("selected-object");
      let parent: HTMLElement | null = match.parentElement;
      while (parent) {
        if (parent instanceof HTMLDetailsElement) parent.open = true;
        parent = parent.parentElement;
      }
      match.scrollIntoView({block: "nearest"});
    }
  }
}

function decodeSummary(encoded: string | null): SceneSummary {
  if (!encoded) throw new Error("The server did not return document metadata.");
  return JSON.parse(atob(encoded.replace(/-/g, "+").replace(/_/g, "/"))) as SceneSummary;
}

function serverError(raw: string): Error {
  return parseApiError(raw);
}

async function responseError(response: Response): Promise<Error> {
  return serverError(await response.text());
}

function setProgress(loaded: number, total: number): void {
  progress.hidden = false;
  const ratio = total > 0 ? loaded / total : 0.12;
  progressFill.style.width = `${Math.max(3, Math.min(100, ratio * 100))}%`;
}

function convert(file: File): Promise<{blob: Blob; summary: SceneSummary; serverMs: number}> {
  return new Promise((resolve, reject) => {
    activeUpload?.abort();
    const request = new XMLHttpRequest();
    activeUpload = request;
    request.open("POST", "/api/v1/documents/preview");
    request.responseType = "blob";
    request.upload.onprogress = event => setProgress(event.loaded, event.total);
    request.upload.onload = () => {
      progressFill.style.width = "100%";
      status.textContent = `Preparing ${file.name}…`;
    };
    request.onload = () => {
      if (activeUpload === request) activeUpload = undefined;
      if (request.status < 200 || request.status >= 300) {
        request.response.text().then((message: string) => reject(serverError(message)));
        return;
      }
      resolve({
        blob: request.response as Blob,
        summary: decodeSummary(request.getResponseHeader("X-IngeTrazo-Summary")),
        serverMs: Number(request.getResponseHeader("X-IngeTrazo-Preview-Milliseconds")) || 0,
      });
    };
    request.onerror = () => {
      if (activeUpload === request) activeUpload = undefined;
      reject(new Error("The server connection failed."));
    };
    request.onabort = () => {
      if (activeUpload === request) activeUpload = undefined;
      reject(new DOMException("The conversion was replaced by a newer request.", "AbortError"));
    };
    const form = new FormData();
    form.append("file", file);
    request.send(form);
  });
}

async function openFile(file: File): Promise<void> {
  if (!file.name.toLowerCase().endsWith(".igz")) {
    status.textContent = "Choose a native .igz document.";
    return;
  }
  const sequence = ++openSequence;
  currentRecord = undefined;
  library.showDocument(undefined);
  selection.clear();
  configureRevisionRestore();
  updatePresentationRevisionState();
  activeFetch?.abort();
  activeFetch = undefined;
  cancelButton.hidden = false;
  status.textContent = `Converting ${file.name}…`;
  summaryElement.replaceChildren();
  setProgress(0, file.size);
  try {
    const converted = await convert(file);
    if (sequence !== openSequence) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(converted.blob);
    loadedDocumentId = undefined;
    await viewer.load(previewUrl);
    if (sequence !== openSequence) return;
    renderSummary(converted.summary);
    addSummary("Preview", `${(converted.blob.size / 1024 / 1024).toFixed(2)} MiB`);
    addSummary("Prepared in", `${(converted.serverMs / 1000).toFixed(2)} s`);
    const projectionName = viewer.applyCamera(converted.summary.camera ?? null);
    if (projectionName) projection.textContent = projectionName;
    empty.hidden = true;
    status.textContent = file.name;
    currentFile = file;
    currentRecord = undefined;
    library.showDocument(undefined);
  library.showDocument(undefined);
    updatePresentationRevisionState();
    saveButton.disabled = false;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    status.textContent = `Could not open the document: ${error instanceof Error ? error.message : String(error)}`;
    empty.hidden = false;
  } finally {
    if (sequence === openSequence) progress.hidden = true;
    if (sequence === openSequence) cancelButton.hidden = true;
  }
}

/** Post one command against the open document and open the revision it produces. */
async function revisionCommand(endpoint: string, body: Record<string, unknown>, message: string): Promise<void> {
  const record = currentRecord;
  if (!record) { notice("No stored document", "Open a stored document first."); return; }
  if (!savePresentationButton.disabled) { status.textContent = "Save or revert presentation changes first."; return; }
  status.textContent = `Saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(`/api/v1/documents/${encodeURIComponent(record.id)}/commands/${endpoint}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({base_revision: record.latest_revision, ...body})});
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    const reported = (revised as {command_result?: {message?: unknown}}).command_result?.message;
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · ${typeof reported === "string" ? reported : message}`;
  } catch (error) {
    notice("That change was refused", error instanceof Error ? error.message : String(error));
    status.textContent = "";
  }
}

async function loadStored(record: DocumentRecord): Promise<void> {
  const sequence = ++openSequence;
  selection.clear();   // ids and face numbers belong to the previous revision
  // A new revision of the open document keeps the camera, so drawing is not interrupted.
  const keepCamera = loadedDocumentId === record.id;
  currentRecord = undefined;
  library.showDocument(undefined);
  configureRevisionRestore();
  updatePresentationRevisionState();
  activeUpload?.abort();
  activeFetch?.abort();
  const controller = new AbortController();
  activeFetch = controller;
  cancelButton.hidden = false;
  status.textContent = `Opening ${record.name}…`;
  const revision = record.revisions.find(item => item.number === record.latest_revision);
  if (!revision) throw new Error("The latest document revision is missing metadata.");
  const response = await fetch(
    `/api/v1/documents/${encodeURIComponent(record.id)}/revisions/${record.latest_revision}/preview`,
    {signal: controller.signal},
  );
  if (!response.ok) throw await responseError(response);
  if (sequence !== openSequence) return;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  const blob = await response.blob();
  previewUrl = URL.createObjectURL(blob);
  await viewer.load(previewUrl, keepCamera);
  if (sequence !== openSequence) return;
  loadedDocumentId = record.id;
  const projectionName = keepCamera ? null : viewer.applyCamera(revision.summary.camera ?? null);
  if (projectionName) projection.textContent = projectionName;
  currentRecord = record;
  library.showDocument(record);
  configureRevisionRestore(record);
  renderSummary(revision.summary);
  addSummary("Preview", `${(blob.size / 1024 / 1024).toFixed(2)} MiB`);
  const serverMs = Number(response.headers.get("X-IngeTrazo-Preview-Milliseconds")) || 0;
  addSummary("Prepared in", `${(serverMs / 1000).toFixed(2)} s`);
  empty.hidden = true;
  currentFile = undefined;
  saveButton.disabled = true;
  status.textContent = `${record.name} · revision ${record.latest_revision}`;
  document.dispatchEvent(new CustomEvent("ingetrazo:loaded"));
  if (activeFetch === controller) activeFetch = undefined;
  if (sequence === openSequence) cancelButton.hidden = true;
}

function renderLibrary(records: DocumentRecord[]): void {
  documentsElement.replaceChildren();
  libraryEmpty.hidden = records.length > 0;
  for (const record of records) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    const actions = document.createElement("div");
    const download = document.createElement("a");
    const name = document.createElement("strong");
    const detail = document.createElement("span");
    name.textContent = record.name;
    detail.textContent = `Revision ${record.latest_revision} · ${new Date(record.updated_at).toLocaleString()}`;
    button.append(name, detail);
    button.addEventListener("click", () => {
      loadStored(record).catch(error => {
        cancelButton.hidden = true;
        if (error instanceof DOMException && error.name === "AbortError") return;
        status.textContent = `Could not open the saved document: ${error instanceof Error ? error.message : String(error)}`;
      });
    });
    download.href = `/api/v1/documents/${encodeURIComponent(record.id)}/revisions/${record.latest_revision}/download`;
    download.download = record.name;
    download.textContent = "Download native .igz";
    actions.className = "document-actions";
    actions.append(download);
    item.append(button, actions);
    documentsElement.append(item);
  }
}

async function refreshLibrary(): Promise<void> {
  libraryEmpty.hidden = false;
  libraryEmpty.textContent = "Loading saved documents…";
  try {
    const response = await fetch("/api/v1/documents");
    if (!response.ok) throw await responseError(response);
    const payload = await response.json() as {documents: DocumentRecord[]};
    libraryEmpty.textContent = "No saved documents.";
    renderLibrary(payload.documents);
  } catch (error) {
    libraryEmpty.hidden = false;
    libraryEmpty.textContent = `Library unavailable: ${error instanceof Error ? error.message : String(error)}`;
  }
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file) void openFile(file);
});

for (const eventName of ["dragenter", "dragover"]) {
  viewport.addEventListener(eventName, event => {
    event.preventDefault();
    viewport.classList.add("drop-target");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  viewport.addEventListener(eventName, event => {
    event.preventDefault();
    viewport.classList.remove("drop-target");
  });
}
viewport.addEventListener("drop", event => {
  const file = event.dataTransfer?.files[0];
  if (file) void openFile(file);
});

document.querySelector<HTMLButtonElement>("#fit")!.addEventListener("click", () => viewer.fit());
document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach(button => {
  button.addEventListener("click", () => viewer.setView(button.dataset.view as "iso" | "top" | "front" | "right"));
});
projection.addEventListener("click", () => { projection.textContent = viewer.toggleProjection(); });
document.querySelector<HTMLInputElement>("#edges")!.addEventListener("change", event => {
  viewer.showEdges((event.currentTarget as HTMLInputElement).checked);
});
document.querySelector<HTMLInputElement>("#grid")!.addEventListener("change", event => {
  viewer.showGrid((event.currentTarget as HTMLInputElement).checked);
});
document.querySelector<HTMLInputElement>("#axes")!.addEventListener("change", event => {
  viewer.showAxes((event.currentTarget as HTMLInputElement).checked);
});
sectionCut.addEventListener("change", applySectionState);
sectionPlane.addEventListener("change", applySectionState);
cancelButton.addEventListener("click", () => {
  openSequence += 1;
  activeUpload?.abort();
  activeFetch?.abort();
  activeUpload = undefined;
  activeFetch = undefined;
  progress.hidden = true;
  cancelButton.hidden = true;
  status.textContent = "Operation cancelled.";
});
savePresentationButton.addEventListener("click", async () => {
  if (!currentRecord) return;
  const record = currentRecord;
  const layers = Object.fromEntries(
    [...layerControls.entries()].map(([name, control]) => [name, control.input.checked]),
  );
  const hiddenObjects = Object.fromEntries(
    [...objectControls.entries()].map(([nativeId, control]) => [nativeId, control.hidden]),
  );
  savePresentationButton.disabled = true;
  status.textContent = `Saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/presentation`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          layers,
          hidden_objects: hiddenObjects,
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    currentRecord = await response.json() as DocumentRecord;
    configureRevisionRestore(currentRecord);
    for (const [name, control] of layerControls) {
      baselineLayerVisibility.set(name, control.input.checked);
    }
    for (const [nativeId, control] of objectControls) {
      baselineObjectHidden.set(nativeId, control.hidden);
    }
    updatePresentationRevisionState();
    status.textContent = `${currentRecord.name} · revision ${currentRecord.latest_revision}`;
    await refreshLibrary();
  } catch (error) {
    status.textContent = `Could not save presentation changes: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
});
moveForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord || !selectedObjectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before moving geometry.";
    return;
  }
  const values = [...moveForm.querySelectorAll<HTMLInputElement>("input")]
    .map(input => Number(input.value));
  if (values.some(value => !Number.isFinite(value)) || values.every(value => value === 0)) {
    status.textContent = "Enter at least one non-zero move distance.";
    return;
  }
  const unitFactor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  const record = currentRecord;
  const objectId = selectedObjectId;
  moveButton.disabled = true;
  status.textContent = `Moving object and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/move-object`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: objectId,
          delta: values.map(value => value * unitFactor),
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · object moved`;
  } catch (error) {
    status.textContent = `Could not move object: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
});
rotateForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord || !selectedObjectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before rotating geometry.";
    return;
  }
  const axis = rotateForm.querySelector<HTMLSelectElement>("select[name=axis]")!.value;
  const degrees = Number(rotateForm.querySelector<HTMLInputElement>("input[name=degrees]")!.value);
  if (!Number.isFinite(degrees) || degrees === 0) {
    status.textContent = "Enter a non-zero rotation angle.";
    return;
  }
  const record = currentRecord;
  rotateButton.disabled = true;
  status.textContent = `Rotating object and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/transform-object`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: selectedObjectId,
          operation: "rotate",
          axis,
          degrees,
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · object rotated`;
  } catch (error) {
    status.textContent = `Could not rotate object: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
});
scaleForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord || !selectedObjectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before scaling geometry.";
    return;
  }
  const factors = [...scaleForm.querySelectorAll<HTMLInputElement>("input")]
    .map(input => Number(input.value));
  if (factors.some(value => !Number.isFinite(value) || value === 0)
      || factors.every(value => value === 1)) {
    status.textContent = "Enter non-zero scale factors with at least one value different from 1.";
    return;
  }
  const record = currentRecord;
  scaleButton.disabled = true;
  status.textContent = `Scaling object and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/transform-object`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: selectedObjectId,
          operation: "scale",
          factors,
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · object scaled`;
  } catch (error) {
    status.textContent = `Could not scale object: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
});
pushPullForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord || !selectedObjectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before pushing geometry.";
    return;
  }
  const direction = pushPullForm.querySelector<HTMLSelectElement>(
    "select[name=direction]",
  )!.value;
  const distance = Number(pushPullForm.querySelector<HTMLInputElement>(
    "input[name=distance]",
  )!.value);
  const keepBase = pushPullForm.querySelector<HTMLInputElement>(
    "input[name=keep_base]",
  )!.checked;
  if (!Number.isFinite(distance) || distance === 0) {
    status.textContent = "Enter a non-zero push/pull distance.";
    return;
  }
  const unitFactor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  const record = currentRecord;
  pushPullButton.disabled = true;
  status.textContent = `Pushing face and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/push-pull`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: selectedObjectId,
          direction,
          distance: distance * unitFactor,
          keep_base: keepBase,
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord & {
      command_result?: {distance: number; limited: boolean};
    };
    await refreshLibrary();
    await loadStored(revised);
    const applied = revised.command_result?.distance ?? distance * unitFactor;
    const appliedDisplay = applied / unitFactor;
    status.textContent = revised.command_result?.limited
      ? `${revised.name} · revision ${revised.latest_revision} · push limited to ${appliedDisplay.toFixed(currentUnits.precision)} ${currentUnits.length}`
      : `${revised.name} · revision ${revised.latest_revision} · face pushed`;
  } catch (error) {
    status.textContent = `Could not push/pull face: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
});
offsetForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord || !selectedObjectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before offsetting geometry.";
    return;
  }
  const distance = Number(offsetForm.querySelector<HTMLInputElement>(
    "input[name=distance]",
  )!.value);
  if (!Number.isFinite(distance) || distance === 0) {
    status.textContent = "Enter a non-zero offset distance.";
    return;
  }
  const unitFactor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  const record = currentRecord;
  offsetButton.disabled = true;
  status.textContent = `Offsetting face and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/offset-face`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: selectedObjectId,
          distance: distance * unitFactor,
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · face offset`;
  } catch (error) {
    status.textContent = `Could not offset face: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
});
async function setObjectMaterial(clear: boolean): Promise<void> {
  if (!currentRecord || !selectedObjectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before changing materials.";
    return;
  }
  const hex = materialForm.querySelector<HTMLInputElement>("input[name=color]")!.value;
  const opacity = Number(materialForm.querySelector<HTMLInputElement>(
    "input[name=opacity]",
  )!.value);
  const color = [1, 3, 5].map(index => Number.parseInt(hex.slice(index, index + 2), 16) / 255);
  if (!clear && (color.some(value => !Number.isFinite(value))
      || !Number.isFinite(opacity) || opacity < 0 || opacity > 1)) {
    status.textContent = "Choose a valid colour and opacity from 0 to 1.";
    return;
  }
  const record = currentRecord;
  materialButton.disabled = true;
  clearMaterialButton.disabled = true;
  status.textContent = `${clear ? "Clearing" : "Applying"} material and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/object-material`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: selectedObjectId,
          clear,
          ...(clear ? {} : {color, opacity}),
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · material ${clear ? "cleared" : "applied"}`;
  } catch (error) {
    status.textContent = `Could not change material: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
}
materialForm.addEventListener("submit", event => {
  event.preventDefault();
  void setObjectMaterial(false);
});
clearMaterialButton.addEventListener("click", () => void setObjectMaterial(true));
async function setObjectIfc(clear: boolean): Promise<void> {
  if (!currentRecord || !selectedObjectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before changing BIM data.";
    return;
  }
  const ifcClass = ifcForm.querySelector<HTMLSelectElement>("select[name=class]")!.value;
  const name = ifcForm.querySelector<HTMLInputElement>("input[name=name]")!.value.trim();
  if (!clear && !name) {
    status.textContent = "Enter a BIM object name.";
    return;
  }
  const record = currentRecord;
  ifcButton.disabled = true;
  clearIfcButton.disabled = true;
  status.textContent = `${clear ? "Removing" : "Applying"} IFC classification and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/object-ifc`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: selectedObjectId,
          clear,
          ...(clear ? {} : {class: ifcClass, name}),
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · IFC classification ${clear ? "removed" : "applied"}`;
  } catch (error) {
    status.textContent = `Could not change IFC classification: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
}
ifcForm.addEventListener("submit", event => {
  event.preventDefault();
  void setObjectIfc(false);
});
clearIfcButton.addEventListener("click", () => void setObjectIfc(true));
async function runObjectLifecycle(
  operation: "duplicate" | "delete" | "rename", objectId = selectedObjectId,
): Promise<void> {
  if (!currentRecord || !objectId) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before editing objects.";
    return;
  }
  const unitFactor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  const delta = [...moveForm.querySelectorAll<HTMLInputElement>("input")]
    .map(input => Number(input.value) * unitFactor);
  if (operation === "duplicate" && delta.some(value => !Number.isFinite(value))) {
    status.textContent = "Enter valid duplicate offsets in the move fields.";
    return;
  }
  const name = objectNameInput.value.trim();
  if (operation === "rename" && !name) {
    status.textContent = "Enter an object name.";
    return;
  }
  const record = currentRecord;
  duplicateButton.disabled = true;
  deleteButton.disabled = true;
  renameButton.disabled = true;
  const operationLabel = operation === "duplicate" ? "Duplicating"
    : operation === "delete" ? "Deleting" : "Renaming";
  status.textContent = `${operationLabel} object and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/object-lifecycle`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          object_id: objectId,
          operation,
          ...(operation === "duplicate" ? {delta} : {}),
          ...(operation === "rename" ? {name} : {}),
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    const completed = operation === "duplicate" ? "duplicated"
      : operation === "delete" ? "deleted" : "renamed";
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · object ${completed}`;
  } catch (error) {
    status.textContent = `Could not ${operation} object: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
}
duplicateButton.addEventListener("click", () => void runObjectLifecycle("duplicate"));
copyButton.addEventListener("click", () => {
  if (!selectedObjectId) return;
  clipboardObjectId = selectedObjectId;
  pasteButton.disabled = false;
  status.textContent = "Object copied. Set the move offset, then paste.";
});
pasteButton.addEventListener("click", () => void runObjectLifecycle("duplicate", clipboardObjectId));
deleteButton.addEventListener("click", () => void runObjectLifecycle("delete"));
renameButton.addEventListener("click", () => void runObjectLifecycle("rename"));
async function restoreAsNew(sourceRevision: number, label: string, history?: "undo" | "redo"): Promise<void> {
  if (!currentRecord) return;
  const record = currentRecord;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/restore-revision`,
      {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision, source_revision: sourceRevision,
          ...(history ? {history} : {}),
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const restored = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(restored);
    status.textContent = `${restored.name} · revision ${restored.latest_revision} · ${label}`;
  } catch (error) {
    status.textContent = `Could not ${label.toLowerCase()}: ${error instanceof Error ? error.message : String(error)}`;
  }
}
undoButton.addEventListener("click", () => {
  const target = currentRecord?.undo?.undo_to;
  if (target) void restoreAsNew(target, `undo to revision ${target}`, "undo");
});
redoButton.addEventListener("click", () => {
  const target = currentRecord?.undo?.redo_to;
  if (target) void restoreAsNew(target, `redo to revision ${target}`, "redo");
});
restoreForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord) return;
  const sourceRevision = Number(restoreSelect.value);
  if (!Number.isInteger(sourceRevision)) return;
  const record = currentRecord;
  status.textContent = `Restoring revision ${sourceRevision}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/restore-revision`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          source_revision: sourceRevision,
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const restored = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(restored);
    status.textContent = `${restored.name} · revision ${restored.latest_revision} restored from revision ${sourceRevision}`;
  } catch (error) {
    status.textContent = `Could not restore revision: ${error instanceof Error ? error.message : String(error)}`;
  }
});
createBoxForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before creating geometry.";
    return;
  }
  const value = (name: string) => Number(
    createBoxForm.querySelector<HTMLInputElement>(`input[name=${name}]`)!.value,
  );
  const size = [value("width"), value("depth"), value("height")];
  const origin = [value("x"), value("y"), value("z")];
  const name = createBoxForm.querySelector<HTMLInputElement>("input[name=name]")!.value.trim();
  if (!name || size.some(item => !Number.isFinite(item) || item <= 0)
      || origin.some(item => !Number.isFinite(item))) {
    status.textContent = "Enter a name, positive box dimensions, and a valid origin.";
    return;
  }
  const unitFactor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  const record = currentRecord;
  createBoxButton.disabled = true;
  status.textContent = `Creating box and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/create-box`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          name,
          size: size.map(item => item * unitFactor),
          origin: origin.map(item => item * unitFactor),
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · box created`;
  } catch (error) {
    status.textContent = `Could not create box: ${error instanceof Error ? error.message : String(error)}`;
    createBoxButton.disabled = false;
  }
});
async function createPlanar(
  form: HTMLFormElement,
  operation: "line" | "rectangle" | "circle" | "arc",
): Promise<void> {
  if (!currentRecord) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before creating geometry.";
    return;
  }
  const value = (name: string) => Number(
    form.querySelector<HTMLInputElement>(`input[name=${name}]`)!.value,
  );
  const origin = [value("x"), value("y"), value("z")];
  const end = operation === "line" ? [value("ex"), value("ey"), value("ez")] : undefined;
  const name = form.querySelector<HTMLInputElement>("input[name=name]")!.value.trim();
  const width = operation === "rectangle" ? value("width") : undefined;
  const depth = operation === "rectangle" ? value("depth") : undefined;
  const radius = operation === "circle" || operation === "arc" ? value("radius") : undefined;
  const segments = operation === "circle" || operation === "arc" ? value("segments") : undefined;
  const startDegrees = operation === "arc" ? value("start_degrees") : undefined;
  const sweepDegrees = operation === "arc" ? value("sweep_degrees") : undefined;
  const plane = form.querySelector<HTMLSelectElement>("select[name=plane]")?.value;
  if (!name || origin.some(item => !Number.isFinite(item))
      || (operation === "line"
        && (end!.some(item => !Number.isFinite(item))
          || end!.every((item, index) => item === origin[index])))
      || (operation === "rectangle"
        && (!Number.isFinite(width) || !Number.isFinite(depth) || width! <= 0 || depth! <= 0))
      || (operation === "circle"
        && (!Number.isFinite(radius) || radius! <= 0 || !Number.isInteger(segments)
          || segments! < 3 || segments! > 256))
      || (operation === "arc"
        && (!Number.isFinite(radius) || radius! <= 0
          || !Number.isFinite(startDegrees) || !Number.isFinite(sweepDegrees)
          || sweepDegrees === 0 || Math.abs(sweepDegrees!) >= 360
          || !Number.isInteger(segments) || segments! < 2 || segments! > 256))) {
    status.textContent = `Enter valid ${operation} dimensions, origin, and name.`;
    return;
  }
  const unitFactor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  const record = currentRecord;
  const button = operation === "line" ? createLineButton
    : operation === "rectangle" ? createRectangleButton
      : operation === "circle" ? createCircleButton : createArcButton;
  button.disabled = true;
  status.textContent = `Creating ${operation} and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/create-planar`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision,
          operation,
          name,
          origin: origin.map(item => item * unitFactor),
          ...(plane ? {plane} : {}),
          ...(operation === "line"
            ? {end: end!.map(item => item * unitFactor)}
            : operation === "rectangle"
              ? {size: [width! * unitFactor, depth! * unitFactor]}
              : operation === "circle"
                ? {radius: radius! * unitFactor, segments}
                : {
                    radius: radius! * unitFactor,
                    start_degrees: startDegrees,
                    sweep_degrees: sweepDegrees,
                    segments,
                  }),
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · ${operation} created`;
  } catch (error) {
    status.textContent = `Could not create ${operation}: ${error instanceof Error ? error.message : String(error)}`;
    button.disabled = false;
  }
}
createLineForm.addEventListener("submit", event => {
  event.preventDefault();
  void createPlanar(createLineForm, "line");
});
createRectangleForm.addEventListener("submit", event => {
  event.preventDefault();
  void createPlanar(createRectangleForm, "rectangle");
});
createCircleForm.addEventListener("submit", event => {
  event.preventDefault();
  void createPlanar(createCircleForm, "circle");
});
createArcForm.addEventListener("submit", event => {
  event.preventDefault();
  void createPlanar(createArcForm, "arc");
});
async function createAnnotation(
  form: HTMLFormElement, operation: "dimension" | "text" | "guide",
): Promise<void> {
  if (!currentRecord) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before creating annotations.";
    return;
  }
  const value = (name: string) => Number(
    form.querySelector<HTMLInputElement>(`input[name=${name}]`)!.value,
  );
  const factor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  let body: Record<string, unknown>;
  if (operation === "dimension") {
    const a = [value("ax"), value("ay"), value("az")];
    const b = [value("bx"), value("by"), value("bz")];
    const offset = [value("ox"), value("oy"), value("oz")];
    if ([...a, ...b, ...offset].some(item => !Number.isFinite(item))
        || b.every((item, index) => item === a[index])) {
      status.textContent = "Enter two different endpoints and a valid dimension offset.";
      return;
    }
    const axis = form.querySelector<HTMLSelectElement>("select[name=axis]")!.value;
    const text = form.querySelector<HTMLInputElement>("input[name=text]")!.value;
    body = {
      operation: "dimension",
      a: a.map(item => item * factor),
      b: b.map(item => item * factor),
      offset: offset.map(item => item * factor),
      axis: axis || null,
      ...(text ? {text} : {}),
    };
  } else if (operation === "text") {
    const anchor = [value("x"), value("y"), value("z")];
    const offset = [value("ox"), value("oy"), value("oz")];
    const text = form.querySelector<HTMLInputElement>("input[name=text]")!.value.trim();
    if (!text || [...anchor, ...offset].some(item => !Number.isFinite(item))) {
      status.textContent = "Enter leader text, an anchor, and a valid offset.";
      return;
    }
    body = {
      operation: "text", text,
      anchor: anchor.map(item => item * factor),
      offset: offset.map(item => item * factor),
    };
  } else {
    const point = [value("x"), value("y"), value("z")];
    const direction = [value("dx"), value("dy"), value("dz")];
    const kind = form.querySelector<HTMLSelectElement>("select[name=kind]")!.value;
    if (point.some(item => !Number.isFinite(item))
        || direction.some(item => !Number.isFinite(item))
        || (kind === "guide-line" && direction.every(item => item === 0))) {
      status.textContent = "Enter a valid guide point and a non-zero line direction.";
      return;
    }
    body = {
      operation: kind,
      point: point.map(item => item * factor),
      ...(kind === "guide-line" ? {direction} : {}),
    };
  }
  const record = currentRecord;
  const button = operation === "dimension" ? createDimensionButton
    : operation === "text" ? createTextButton : createGuideButton;
  button.disabled = true;
  status.textContent = `Creating ${operation} and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/create-annotation`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({base_revision: record.latest_revision, ...body}),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · ${operation} created`;
  } catch (error) {
    status.textContent = `Could not create ${operation}: ${error instanceof Error ? error.message : String(error)}`;
    button.disabled = false;
  }
}
createDimensionForm.addEventListener("submit", event => {
  event.preventDefault();
  void createAnnotation(createDimensionForm, "dimension");
});
createTextForm.addEventListener("submit", event => {
  event.preventDefault();
  void createAnnotation(createTextForm, "text");
});
createGuideForm.addEventListener("submit", event => {
  event.preventDefault();
  void createAnnotation(createGuideForm, "guide");
});
async function postGeospatial(
  endpoint: "set-georef" | "set-map" | "import-terrain" | "import-survey" | "create-geopath",
  body: Record<string, unknown>, button: HTMLButtonElement, label: string,
): Promise<void> {
  if (!currentRecord) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before editing geospatial data.";
    return;
  }
  const record = currentRecord;
  button.disabled = true;
  status.textContent = `${label} and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/${endpoint}`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({base_revision: record.latest_revision, ...body}),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · ${label.toLowerCase()}`;
  } catch (error) {
    status.textContent = `Could not ${label.toLowerCase()}: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
}
georefForm.addEventListener("submit", event => {
  event.preventDefault();
  const number = (name: string) => Number(
    georefForm.querySelector<HTMLInputElement>(`input[name=${name}]`)!.value,
  );
  const latitude = number("latitude");
  const longitude = number("longitude");
  const altitude = number("altitude");
  const north = number("north");
  if (![latitude, longitude, altitude, north].every(Number.isFinite)
      || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
    status.textContent = "Enter a valid WGS84 latitude, longitude, altitude, and north angle.";
    return;
  }
  void postGeospatial(
    "set-georef", {latitude, longitude, altitude, north}, georefButton, "Saving datum",
  );
});
mapForm.addEventListener("submit", event => {
  event.preventDefault();
  const zoom = Number(mapForm.querySelector<HTMLInputElement>("input[name=zoom]")!.value);
  const radius = Number(mapForm.querySelector<HTMLInputElement>("input[name=radius]")!.value);
  const opacity = Number(mapForm.querySelector<HTMLInputElement>("input[name=opacity]")!.value);
  if (!Number.isInteger(zoom) || zoom < 1 || zoom > 19
      || !Number.isFinite(radius) || radius < 10 || radius > 100000
      || !Number.isFinite(opacity) || opacity < 0 || opacity > 1) {
    status.textContent = "Choose a valid map zoom, capture radius, and opacity.";
    return;
  }
  void postGeospatial("set-map", {
    source: mapForm.querySelector<HTMLSelectElement>("select[name=source]")!.value,
    zoom, radius, opacity,
  }, mapButton, "Saving map");
});
clearMapButton.addEventListener("click", () => {
  void postGeospatial("set-map", {clear: true}, clearMapButton, "Removing map");
});
terrainForm.addEventListener("submit", event => {
  event.preventDefault();
  const columns = Number(terrainForm.querySelector<HTMLInputElement>("input[name=columns]")!.value);
  const text = terrainForm.querySelector<HTMLTextAreaElement>("textarea[name=text]")!.value.trim();
  if (!Number.isInteger(columns) || columns < 2 || columns > 100 || !text) {
    status.textContent = "Enter a column count and a row-major XYZ grid.";
    return;
  }
  void postGeospatial(
    "import-terrain", {columns, text}, terrainButton, "Importing terrain",
  );
});
surveyForm.addEventListener("submit", event => {
  event.preventDefault();
  const text = surveyForm.querySelector<HTMLTextAreaElement>("textarea[name=text]")!.value.trim();
  const zone = Number(surveyForm.querySelector<HTMLInputElement>("input[name=zone]")!.value);
  const northern = surveyForm.querySelector<HTMLSelectElement>("select[name=hemisphere]")!.value === "N";
  if (!text || !Number.isInteger(zone) || zone < 1 || zone > 60) {
    status.textContent = "Paste survey rows and choose a UTM zone from 1 to 60.";
    return;
  }
  void postGeospatial(
    "import-survey", {text, zone, northern}, surveyButton, "Importing survey",
  );
});
geopathForm.addEventListener("submit", event => {
  event.preventDefault();
  const name = geopathForm.querySelector<HTMLInputElement>("input[name=name]")!.value.trim();
  const raw = geopathForm.querySelector<HTMLTextAreaElement>("textarea[name=points]")!.value;
  const factor = currentUnits.length === "mm" ? 0.001
    : currentUnits.length === "cm" ? 0.01
      : currentUnits.length === "ft" ? 0.3048
        : currentUnits.length === "in" ? 0.0254 : 1;
  const points = raw.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map(line =>
    line.split(/[;,\s]+/).map(value => Number(value) * factor),
  );
  const closed = geopathForm.querySelector<HTMLInputElement>("input[name=closed]")!.checked;
  const surfaceValue = geopathForm.querySelector<HTMLSelectElement>("select[name=surface]")!.value;
  if (!name || points.length < 2 || points.some(point => point.length !== 3
      || point.some(value => !Number.isFinite(value)))) {
    status.textContent = "Enter a path name and at least two local X,Y,Z lines.";
    return;
  }
  void postGeospatial(
    "create-geopath",
    {name, points, closed, surface: surfaceValue || null},
    geopathButton, "Creating path",
  );
});
async function postDisplay(
  endpoint: "set-style" | "set-shadows", body: Record<string, unknown>,
  button: HTMLButtonElement, label: string,
): Promise<void> {
  if (!currentRecord) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before changing the display.";
    return;
  }
  const record = currentRecord;
  button.disabled = true;
  status.textContent = `${label} and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/${endpoint}`,
      {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({base_revision: record.latest_revision, ...body}),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · ${label.toLowerCase()}`;
  } catch (error) {
    status.textContent = `Could not ${label.toLowerCase()}: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
}
styleForm.addEventListener("submit", event => {
  event.preventDefault();
  const name = styleForm.querySelector<HTMLSelectElement>("select[name=name]")!.value;
  void postDisplay("set-style", {name}, styleButton, "Applying style");
});
shadowForm.addEventListener("submit", event => {
  event.preventDefault();
  const integer = (name: string) => Number(
    shadowForm.querySelector<HTMLInputElement>(`input[name=${name}]`)!.value,
  );
  const month = integer("month");
  const day = integer("day");
  const hour = integer("hour");
  const minute = integer("minute");
  const darkness = Number(shadowForm.querySelector<HTMLInputElement>("input[name=darkness]")!.value);
  const offsetInput = shadowForm.querySelector<HTMLInputElement>("input[name=utc_offset]")!;
  const utcOffset = offsetInput.value.trim() === "" ? null : Number(offsetInput.value);
  if (![month, day, hour, minute].every(Number.isInteger)
      || month < 1 || month > 12 || day < 1 || day > 31
      || hour < 0 || hour > 23 || minute < 0 || minute > 59
      || !Number.isFinite(darkness) || darkness < 0 || darkness > 1
      || (utcOffset !== null && (!Number.isInteger(utcOffset) || utcOffset < -14 || utcOffset > 14))) {
    status.textContent = "Enter a valid date, local time, darkness, and optional UTC offset.";
    return;
  }
  void postDisplay("set-shadows", {
    enabled: shadowForm.querySelector<HTMLInputElement>("input[name=enabled]")!.checked,
    month, day, hour, minute, darkness, utc_offset: utcOffset,
  }, shadowButton, "Saving sun study");
});
sheetForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!currentRecord) return;
  if (!savePresentationButton.disabled) {
    status.textContent = "Save or revert presentation changes before creating a sheet.";
    return;
  }
  const name = sheetForm.querySelector<HTMLInputElement>("input[name=name]")!.value.trim();
  const scale = Number(sheetForm.querySelector<HTMLInputElement>("input[name=scale]")!.value);
  if (!name || !Number.isFinite(scale) || scale < 0.1 || scale > 100000) {
    status.textContent = "Enter a sheet name and a valid scale denominator.";
    return;
  }
  const record = currentRecord;
  sheetButton.disabled = true;
  status.textContent = `Creating sheet and saving revision ${record.latest_revision + 1}…`;
  try {
    const response = await fetch(
      `/api/v1/documents/${encodeURIComponent(record.id)}/commands/create-sheet`,
      {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          base_revision: record.latest_revision, name, scale,
          paper: sheetForm.querySelector<HTMLSelectElement>("select[name=paper]")!.value,
          view: sheetForm.querySelector<HTMLSelectElement>("select[name=view]")!.value,
          landscape: sheetForm.querySelector<HTMLInputElement>("input[name=landscape]")!.checked,
        }),
      },
    );
    if (!response.ok) throw await responseError(response);
    const revised = await response.json() as DocumentRecord;
    await refreshLibrary();
    await loadStored(revised);
    status.textContent = `${revised.name} · revision ${revised.latest_revision} · sheet created`;
  } catch (error) {
    status.textContent = `Could not create sheet: ${error instanceof Error ? error.message : String(error)}`;
    updatePresentationRevisionState();
  }
});
viewer.onSelection = selection => { renderSelection(selection); toolForms.refreshSelection(true); };
viewer.onMeasurement = renderMeasurement;
viewer.onSketchPoint = (point, inference) => {
  const names = sketchLineStart ? ["ex", "ey", "ez"] : ["x", "y", "z"];
  names.forEach((name, index) => {
    createLineForm.querySelector<HTMLInputElement>(`input[name=${name}]`)!.value =
      String(point[index]);
  });
  if (!sketchLineStart) {
    sketchLineStart = point;
    status.textContent = `Line start snapped to ${inference}; choose the endpoint.`;
    return;
  }
  sketchLineStart = undefined;
  viewer.setSketchMode(false);
  sketchLineButton.classList.remove("active");
  sketchLineButton.textContent = "Sketch line";
  status.textContent = `Line endpoint snapped to ${inference}; creating native line…`;
  void createPlanar(createLineForm, "line");
};
document.querySelector<HTMLButtonElement>("#clear-selection")!.addEventListener("click", () => viewer.clearSelection());
measureButton.addEventListener("click", () => {
  const enabled = !measureButton.classList.contains("active");
  sketchLineStart = undefined;
  sketchLineButton.classList.remove("active");
  sketchLineButton.textContent = "Sketch line";
  viewer.setSketchMode(false);
  measureButton.classList.toggle("active", enabled);
  measureButton.textContent = enabled ? "Cancel measure" : "Measure";
  viewer.setMeasureMode(enabled);
  if (enabled) status.textContent = "Choose the first measurement point.";
});
sketchLineButton.addEventListener("click", () => {
  const enabled = !sketchLineButton.classList.contains("active");
  sketchLineStart = undefined;
  sketchLineButton.classList.toggle("active", enabled);
  sketchLineButton.textContent = enabled ? "Cancel line" : "Sketch line";
  measureButton.classList.remove("active");
  measureButton.textContent = "Measure";
  viewer.setSketchMode(enabled);
  if (enabled) status.textContent = "Choose a model vertex, surface, or ground-plane point.";
});
document.querySelector<HTMLButtonElement>("#clear-measurement")!.addEventListener(
  "click", () => viewer.clearMeasurement(),
);

saveButton.addEventListener("click", async () => {
  if (!currentFile) return;
  saveButton.disabled = true;
  status.textContent = `Saving ${currentFile.name}…`;
  const body = new FormData();
  body.append("file", currentFile);
  try {
    const response = await fetch("/api/v1/documents", {method: "POST", body});
    if (!response.ok) throw await responseError(response);
    const record = await response.json() as DocumentRecord;
    status.textContent = `${record.name} saved as revision 1.`;
    currentFile = undefined;
    await refreshLibrary();
  } catch (error) {
    status.textContent = `Could not save the document: ${error instanceof Error ? error.message : String(error)}`;
    saveButton.disabled = false;
  }
});

document.querySelector<HTMLButtonElement>("#refresh")!.addEventListener("click", () => void refreshLibrary());
void refreshLibrary();

void initLanguage();

document.addEventListener("ingetrazo:run-extension", event => {
  const {key, name, params} = (event as CustomEvent<{key: string; name: string; params: Record<string, unknown>}>).detail;
  void revisionCommand("run-extension", {extension: key, params}, `${name} ran`);
});

document.addEventListener("ingetrazo:open-document", async event => {
  const id = (event as CustomEvent<string>).detail;
  const response = await fetch(`/api/v1/documents/${encodeURIComponent(id)}`);
  if (!response.ok) { status.textContent = "The document could not be opened."; return; }
  const record = await response.json() as DocumentRecord;
  await refreshLibrary();
  await loadStored(record);
});
document.addEventListener("ingetrazo:export", () => void exportRevision(currentRecord));

document.addEventListener("ingetrazo:signed-in", () => void refreshLibrary());
document.addEventListener("ingetrazo:sign-out", async () => {
  const who = await whoAmI();
  if (!who.auth_required) { status.textContent = "This server has no user accounts; there is nothing to sign out of."; return; }
  await signOut();
});

// Preferences that change what is on screen right away.
const applyPrefs = () => {
  const p = prefs();
  viewer.setNavigationPrefs(p);
  refreshUnits();
  document.dispatchEvent(new CustomEvent("ingetrazo:units-changed"));
};
onPrefsChange(applyPrefs);
applyPrefs();
