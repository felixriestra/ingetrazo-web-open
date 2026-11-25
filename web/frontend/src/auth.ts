/**
 * Signing in, when the server has accounts.
 *
 * Wraps ``fetch`` once: a ``401`` from the API opens a small sign-in dialog (the user's
 * access token, traded for a session cookie), then the request that failed is repeated.
 * With accounts off the server never answers 401 and none of this appears.
 */
let pending: Promise<boolean> | undefined;
const original = window.fetch.bind(window);

function askToken(message: string): Promise<string | null> {
  return new Promise(resolve => {
    const dialog = document.createElement("dialog");
    dialog.className = "shortcut-dialog";
    const form = document.createElement("form");
    form.method = "dialog";
    const note = Object.assign(document.createElement("p"), {className: "muted", textContent: message});
    const label = document.createElement("label");
    label.textContent = "Access token ";
    const input = Object.assign(document.createElement("input"), {type: "password", autocomplete: "current-password", maxLength: 200, required: true});
    label.append(input);
    const buttons = document.createElement("div");
    buttons.className = "dialog-buttons";
    buttons.append(Object.assign(document.createElement("button"), {type: "submit", textContent: "Sign in"}));
    form.append(Object.assign(document.createElement("h2"), {textContent: "Sign in to IngeTrazo"}), note, label, buttons);
    let token: string | null = null;
    form.addEventListener("submit", () => { token = input.value.trim() || null; });
    dialog.addEventListener("cancel", event => event.preventDefault());         // the service is unusable without it
    dialog.addEventListener("close", () => { dialog.remove(); resolve(token); });
    dialog.append(form);
    document.body.append(dialog);
    dialog.showModal();
    queueMicrotask(() => input.focus());
  });
}

async function signIn(): Promise<boolean> {
  let message = "This server asks you to sign in. Your administrator gives you an access token.";
  for (;;) {
    const token = await askToken(message);
    if (token === null) return false;
    const response = await original("/api/v1/auth/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({token})});
    if (response.ok) {
      document.dispatchEvent(new CustomEvent("ingetrazo:signed-in"));
      return true;
    }
    try { message = (await response.json() as {detail?: {message?: string}}).detail?.message ?? "That token did not work."; }
    catch { message = "That token did not work."; }
  }
}

window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const response = await original(input, init);
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (response.status !== 401 || !url.includes("/api/") || url.includes("/api/v1/auth/")) return response;
  pending ??= signIn().finally(() => { pending = undefined; });
  return (await pending) ? original(input, init) : response;
};

/** Who is signed in, and whether the server wants anyone to be. */
export async function whoAmI(): Promise<{auth_required: boolean; authenticated: boolean; user?: string; role?: string}> {
  try { return await (await original("/api/v1/auth/me")).json(); }
  catch { return {auth_required: false, authenticated: true}; }
}

export async function signOut(): Promise<void> {
  await original("/api/v1/auth/logout", {method: "POST"});
  location.reload();
}
