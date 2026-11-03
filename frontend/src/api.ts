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
