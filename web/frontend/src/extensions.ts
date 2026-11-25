/**
 * Extensions menu: scripts the server's operator installed (see
 * ``web/backend/ingetrazo_web/extensions.py``). Choosing one opens a form built from
 * its declared parameters; running it is one revision of the open document.
 */
export interface ExtensionParameter {
  name: string; label: string; type: "int" | "number" | "text" | "bool" | "choice";
  default: unknown; min?: number; max?: number; choices?: string[];
}
export interface ExtensionInfo {key: string; name: string; description: string; parameters: ExtensionParameter[]; error: string | null}
export interface ExtensionListing {directory: string; extensions: ExtensionInfo[]}

export async function listExtensions(): Promise<ExtensionListing> {
  try {
    const response = await fetch("/api/v1/extensions");
    if (response.ok) return await response.json() as ExtensionListing;
  } catch { /* offline */ }
  return {directory: "", extensions: []};
}

/** Ask for the extension's parameters; resolves them, or ``null`` when cancelled. */
export function askParameters(extension: ExtensionInfo): Promise<Record<string, unknown> | null> {
  return new Promise(resolve => {
    const dialog = document.createElement("dialog");
    dialog.className = "shortcut-dialog";
    const form = document.createElement("form");
    form.method = "dialog";
    form.append(Object.assign(document.createElement("h2"), {textContent: extension.name}));
    if (extension.description) form.append(Object.assign(document.createElement("p"), {className: "muted", textContent: extension.description}));
    const readers: (() => [string, unknown])[] = [];
    for (const parameter of extension.parameters) {
      const label = document.createElement("label");
      label.className = "composer-field";
      label.append(Object.assign(document.createElement("span"), {textContent: parameter.label}));
      let input: HTMLInputElement | HTMLSelectElement;
      if (parameter.type === "bool") {
        input = Object.assign(document.createElement("input"), {type: "checkbox", checked: parameter.default === true});
        readers.push(() => [parameter.name, (input as HTMLInputElement).checked]);
      } else if (parameter.type === "choice") {
        const select = document.createElement("select");
        for (const choice of parameter.choices ?? []) select.append(new Option(choice, choice, false, choice === parameter.default));
        input = select;
        readers.push(() => [parameter.name, select.value]);
      } else if (parameter.type === "text") {
        input = Object.assign(document.createElement("input"), {type: "text", value: String(parameter.default ?? ""), maxLength: 1000});
        readers.push(() => [parameter.name, (input as HTMLInputElement).value]);
      } else {
        input = Object.assign(document.createElement("input"), {type: "number", value: String(parameter.default ?? ""), step: parameter.type === "int" ? "1" : "any"});
        if (parameter.min !== undefined) (input as HTMLInputElement).min = String(parameter.min);
        if (parameter.max !== undefined) (input as HTMLInputElement).max = String(parameter.max);
        readers.push(() => [parameter.name, (input as HTMLInputElement).valueAsNumber]);
      }
      label.append(input);
      form.append(label);
    }
    const buttons = document.createElement("div");
    buttons.className = "dialog-buttons";
    const cancel = Object.assign(document.createElement("button"), {type: "button", textContent: "Cancel"});
    cancel.addEventListener("click", () => dialog.close());
    buttons.append(cancel, Object.assign(document.createElement("button"), {type: "submit", textContent: "Run"}));
    form.append(buttons);
    let answer: Record<string, unknown> | null = null;
    form.addEventListener("submit", () => { answer = Object.fromEntries(readers.map(read => read())); });
    dialog.addEventListener("close", () => { dialog.remove(); resolve(answer); });
    dialog.append(form);
    document.body.append(dialog);
    dialog.showModal();
  });
}
