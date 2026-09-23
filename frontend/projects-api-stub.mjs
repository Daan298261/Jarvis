export class ApiError extends Error {
  constructor(status, message, body = null) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

export function isApiError(err) {
  return err instanceof ApiError
}

export async function api(path, init) {
  if (typeof globalThis.__projectsApi !== "function") {
    throw new Error("missing __projectsApi")
  }
  return globalThis.__projectsApi(path, init)
}
