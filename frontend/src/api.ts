import type { Answer } from './session/format.ts'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export interface HealthResponse {
  status: string
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/api/health`)
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return response.json()
}

/** Where the backend gets study sessions from: its built-in sample, or the agent that calls Claude. */
export async function getTutorSource(): Promise<'sample' | 'agent'> {
  const response = await fetch(`${API_BASE}/api/tutor`)
  if (!response.ok) throw new Error(`Tutor check failed: ${response.status}`)
  const reply = (await response.json()) as { source?: string }
  return reply.source === 'agent' ? 'agent' : 'sample'
}

/** A request to the backend that failed, with a message fit to show the student. */
export class ApiError extends Error {
  /** The HTTP status, or null when the backend could not be reached at all. */
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function post(path: string, body?: unknown): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError("The backend can't be reached. Check that it is running.", null)
  }
  if (!response.ok) {
    // FastAPI puts the reason in `detail`: a sentence for our own errors, a list for a malformed body.
    const detail: unknown = await response
      .json()
      .then((reply: { detail?: unknown }) => reply.detail)
      .catch(() => undefined)
    throw new ApiError(typeof detail === 'string' ? detail : `The backend refused the request (${response.status}).`, response.status)
  }
  return response.json()
}

/** A PDF of the student's notes, base64-encoded. */
export interface NotesUpload {
  filename: string
  data: string
}

// Study sessions; see docs/session_format.md. Replies are returned unchecked:
// the caller checks them against the format and the loaded model.

export function startSession(request: string, notes: NotesUpload | null): Promise<unknown> {
  return post('/api/sessions', { request, notes })
}

export function nextPart(sessionId: string): Promise<unknown> {
  return post(`/api/sessions/${sessionId}/next`)
}

export function sendAnswer(sessionId: string, answer: Answer): Promise<unknown> {
  return post(`/api/sessions/${sessionId}/answers`, answer)
}

export function finishSession(sessionId: string): Promise<unknown> {
  return post(`/api/sessions/${sessionId}/finish`)
}
