// API client for /api/v1/admin. The session lives in an HttpOnly cookie;
// the CSRF token is kept in memory only and sent with every write.

const BASE = "/api/v1";
let csrf = null;

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function setCsrf(token) {
  csrf = token;
}

async function request(method, path, body) {
  const headers = { Accept: "application/json" };
  const form = body instanceof FormData;
  if (method !== "GET") {
    if (!form) headers["Content-Type"] = "application/json";
    headers["X-Request-ID"] = crypto.randomUUID();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const response = await fetch(BASE + path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined || form ? body : JSON.stringify(body),
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data?.error ?? {};
    throw new ApiError(
      response.status,
      error.code ?? "request_failed",
      error.message ?? `Request failed (${response.status})`,
    );
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  put: (path, body = {}) => request("PUT", path, body),
};

export function query(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
