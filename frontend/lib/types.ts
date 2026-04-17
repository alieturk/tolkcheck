export type SessionStatus =
  | "pending"
  | "transcribing"
  | "diarising"
  | "awaiting_role_confirmation"
  | "scoring"
  | "generating"
  | "completed"
  | "failed";

export interface Session {
  id: string;
  filename: string;
  audio_path: string;
  language: string;
  ind_case_id: string | null;
  status: SessionStatus;
  duration_seconds: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  speaker: string;
  text: string;
}

export interface Evaluation {
  id: string;
  session_id: string;
  transcript: TranscriptSegment[] | null;
  interpreter_speaker: string | null;
  client_speaker: string | null;
  overall_score: number | null;
  accuracy_score: number | null;
  completeness_score: number | null;
  terminology_score: number | null;
  fluency_score: number | null;
  semantic_similarity_scores: number[] | null;
  llm_feedback: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  session_id: string;
  status: SessionStatus;
}

export interface ConfirmRolesResponse {
  session_id: string;
  status: SessionStatus;
}
