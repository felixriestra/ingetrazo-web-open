/**
 * Reading the API's error bodies in one place.
 *
 * Every non-2xx response is ``{"detail": {"code", "message", "fields"?}}`` (see
 * ``web/backend/ingetrazo_web/errors.py``). Older text bodies, and proxies' plain text,
 * are still understood so a deployment in front of the service cannot blank the message.
 */
export interface ApiErrorField {field: string; message: string}

export class ApiError extends Error {
  constructor(message: string, readonly code = "error", readonly fields: ApiErrorField[] = [], readonly status = 0) {
    super(message);
    this.name = "ApiError";
  }
}

/** The error a failed response describes. */
export function parseApiError(raw: string, status = 0): ApiError {
  try {
    const detail = (JSON.parse(raw) as {detail?: unknown}).detail;
    if (typeof detail === "string") return new ApiError(detail, "error", [], status);
    if (Array.isArray(detail)) {                 // FastAPI's own validation list, if a handler was bypassed
      const fields = detail.map(item => ({field: String((item as {loc?: unknown[]}).loc?.slice(1).join(".") ?? ""), message: String((item as {msg?: unknown}).msg ?? "")}));
      return new ApiError(fields.map(item => `${item.field} ${item.message}`.trim()).join("; ") || "The request is not valid.", "invalid_request", fields, status);
    }
    if (detail && typeof detail === "object") {
      const body = detail as {code?: unknown; message?: unknown; fields?: unknown};
      if (typeof body.message === "string") {
        const fields = Array.isArray(body.fields) ? body.fields.filter((item): item is ApiErrorField => typeof (item as ApiErrorField)?.message === "string") : [];
        return new ApiError(body.message, typeof body.code === "string" ? body.code : "error", fields, status);
      }
    }
  } catch {
    // A proxy or development server may return plain text instead of JSON.
  }
  return new ApiError(raw.trim().slice(0, 500) || "The server could not complete the request.", "error", [], status);
}

export async function responseApiError(response: Response): Promise<ApiError> {
  return parseApiError(await response.text(), response.status);
}
