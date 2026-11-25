/**
 * Materials section: the texture library (pick a swatch, then paint objects with it).
 * The components library has its own section (see components.ts).
 */
interface TextureItem {file: string; name: string}
interface TextureCategory {id: string; items: TextureItem[]}

export interface Library {
  /** Library texture the Paint tool applies, if one was chosen. */
  activeTexture: () => string | undefined;
  /** A material of the open document (imported from .igmat or .skm) the Paint tool applies. */
  activeMaterial: () => string | undefined;
  clearTexture: () => void;
  /** Show the materials of this revision of the open document (none when closed). */
  showDocument: (record: {id: string; latest_revision: number} | undefined) => void;
}

/** What the document-materials section needs from the page. */
export interface LibraryHost {
  applyRevision: (revised: unknown, message: string) => Promise<void>;
  setStatus: (text: string) => void;
}

interface DocumentMaterial {name: string; color: [number, number, number] | null; textured: boolean}

/** Ask the toolbar to switch tools (it owns activation). */
export function requestTool(key: string): void {
  document.dispatchEvent(new CustomEvent("ingetrazo:activate", {detail: key}));
}

export function mountLibrary(host: LibraryHost): Library {
  const panel = document.querySelector<HTMLElement>("#materials-panel")!;
  let texture: string | undefined;
  let documentMaterial: string | undefined;
  let record: {id: string; latest_revision: number} | undefined;
  let swatches: HTMLElement | undefined;

  const materials = document.createElement("div");
  const picker = document.createElement("select");
  picker.setAttribute("aria-label", "Texture category");
  const current = document.createElement("p");
  current.className = "muted";
  const useColour = document.createElement("button");
  useColour.type = "button";
  useColour.className = "link-button";
  useColour.textContent = "Paint with a colour instead";
  useColour.addEventListener("click", () => { texture = undefined; documentMaterial = undefined; showCurrent(); renderDocument(); swatches?.querySelectorAll(".active").forEach(node => node.classList.remove("active")); });
  panel.append(picker, current, useColour, materials);

  // The open document's own materials: paint by name, import .igmat/.skm, export .igmat.
  const own = document.createElement("div");
  own.className = "document-materials";
  const ownTitle = document.createElement("p");
  ownTitle.className = "muted";
  const ownList = document.createElement("div");
  ownList.className = "swatch-grid";
  const importButton = document.createElement("button");
  importButton.type = "button";
  importButton.textContent = "Import material file (.igmat, .skm)…";
  const exportLink = document.createElement("a");
  exportLink.textContent = "Export document materials (.igmat)";
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = ".igmat,.skm";
  fileInput.hidden = true;
  own.append(ownTitle, ownList, importButton, exportLink, fileInput);
  panel.append(own);
  let ownMaterials: DocumentMaterial[] = [];

  importButton.addEventListener("click", () => {
    if (!record) { host.setStatus("Open a stored document first."); return; }
    fileInput.click();
  });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    fileInput.value = "";
    if (!file || !record) return;
    const body = new FormData();
    body.append("base_revision", String(record.latest_revision));
    body.append("file", file);
    host.setStatus(`Importing ${file.name}…`);
    const response = await fetch(`/api/v1/documents/${encodeURIComponent(record.id)}/materials/import`, {method: "POST", body});
    if (!response.ok) {
      const detail = await response.json().catch(() => ({})) as {detail?: unknown};
      host.setStatus(`Could not import ${file.name}: ${typeof detail.detail === "string" ? detail.detail : response.statusText}`);
      return;
    }
    await host.applyRevision(await response.json(), `materials imported from ${file.name}`);
  });

  function renderDocument(): void {
    ownList.replaceChildren();
    ownTitle.textContent = !record ? "Open a document to see its own materials."
      : ownMaterials.length ? "In this document (paints loose faces and faces inside an open group):"
        : "This document has no named materials yet.";
    exportLink.hidden = !record || !ownMaterials.length;
    importButton.disabled = !record;
    if (record) exportLink.href = `/api/v1/documents/${encodeURIComponent(record.id)}/revisions/${record.latest_revision}/materials.igmat`;
    for (const item of ownMaterials) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "swatch";
      button.title = item.textured ? `${item.name} (textured)` : item.name;
      button.setAttribute("aria-label", button.title);
      button.classList.toggle("active", item.name === documentMaterial);
      const [r, g, b] = item.color ?? [0.7, 0.7, 0.7];
      button.style.background = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
      button.textContent = item.textured ? "T" : "";
      button.addEventListener("click", () => {
        documentMaterial = item.name;
        texture = undefined;
        showCurrent();
        renderDocument();
        swatches?.querySelectorAll(".active").forEach(node => node.classList.remove("active"));
        requestTool("paint");
      });
      ownList.append(button);
    }
  }

  async function loadDocument(): Promise<void> {
    ownMaterials = [];
    if (record) {
      const response = await fetch(`/api/v1/documents/${encodeURIComponent(record.id)}/revisions/${record.latest_revision}/materials`);
      if (response.ok) ownMaterials = (await response.json() as {materials: DocumentMaterial[]}).materials;
    }
    if (documentMaterial && !ownMaterials.some(item => item.name === documentMaterial)) documentMaterial = undefined;
    renderDocument();
    showCurrent();
  }

  function showCurrent(): void {
    current.textContent = documentMaterial ? `Painting with the document material ${documentMaterial}. Choose Paint and click faces.`
      : texture ? `Painting with ${texture}. Choose Paint and click objects.` : "Pick a texture, then click objects with the Paint tool.";
  }
  showCurrent();

  async function loadMaterials(): Promise<void> {
    const response = await fetch("/api/v1/library/materials");
    if (!response.ok) return;
    const {categories} = await response.json() as {categories: TextureCategory[]};
    const shown = categories.filter(category => category.items.length);
    for (const category of shown) picker.append(new Option(`${category.id} (${category.items.length})`, category.id));
    const render = () => {
      swatches?.remove();
      swatches = document.createElement("div");
      swatches.className = "swatch-grid";
      const category = shown.find(item => item.id === picker.value);
      for (const item of category?.items ?? []) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "swatch";
        button.title = item.name;
        button.classList.toggle("active", item.file === texture);
        const image = document.createElement("img");
        image.src = `/api/v1/library/materials/file/${item.file}`;
        image.alt = item.name;
        image.loading = "lazy";
        image.width = 44;
        image.height = 44;
        button.append(image);
        button.addEventListener("click", () => {
          texture = item.file;
          documentMaterial = undefined;
          showCurrent();
          renderDocument();
          render();
          requestTool("paint");
        });
        swatches.append(button);
      }
      materials.append(swatches);
    };
    picker.addEventListener("change", render);
    render();
  }

  void loadMaterials();
  renderDocument();
  return {
    activeTexture: () => texture,
    activeMaterial: () => documentMaterial,
    clearTexture: () => { texture = undefined; documentMaterial = undefined; showCurrent(); renderDocument(); },
    showDocument: next => { record = next; void loadDocument(); },
  };
}
