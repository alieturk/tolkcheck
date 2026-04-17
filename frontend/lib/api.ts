import type {
  ConfirmRolesResponse,
  Evaluation,
  Session,
  UploadResponse,
} from "./types";

const BASE = "/api/backend";

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadSession(
  file: File,
  language: string,
  caseId?: string,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("audio", file);
  form.append("language", language);
  if (caseId) form.append("case_id", caseId);

  return request<UploadResponse>("/sessions", { method: "POST", body: form });
}

export async function listSessions(
  limit = 50,
  offset = 0,
): Promise<Session[]> {
  return request<Session[]>(`/sessions?limit=${limit}&offset=${offset}`);
}

export async function getSession(id: string): Promise<Session> {
  return request<Session>(`/sessions/${id}`);
}

export async function getEvaluation(id: string): Promise<Evaluation> {
  return request<Evaluation>(`/evaluations/${id}`);
}

export async function confirmRoles(
  sessionId: string,
  interpreterSpeaker: string,
  clientSpeaker: string,
): Promise<ConfirmRolesResponse> {
  return request<ConfirmRolesResponse>(
    `/sessions/${sessionId}/confirm-roles`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        interpreter_speaker: interpreterSpeaker,
        client_speaker: clientSpeaker,
      }),
    },
  );
}
