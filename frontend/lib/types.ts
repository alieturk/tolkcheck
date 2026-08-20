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
  known_terms: string | null;
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
  language?: string;
}

export interface IssueItem {
  type: "omission" | "addition" | "mistranslation" | "false-negative";
  severity: "critical" | "high" | "medium" | "low";
  description: string;
  originalPhrase?: string;
  translatedPhrase?: string;
}

export type PairDirection = "client_to_officer" | "officer_to_client";

export interface PairIssues {
  pair_index: number;
  // pair_index is numbered per direction, so a client_to_officer pair and an
  // officer_to_client pair can both be index 0. Always key on both fields.
  direction?: PairDirection;
  issues: IssueItem[];
}

/** One speaker block as produced by the backend's services/alignment.py. */
export interface AlignedBlock {
  role: "client" | "interpreter" | "officer";
  speaker: string;
  start: number;
  end: number;
  text: string;
  language?: string;
  /** Interpreter blocks only: which way this block was translating. */
  direction?: "to_client" | "to_officer" | null;
  /** Interpreter blocks only, when paired: index within its direction's pair list. */
  pair_index?: number;
  /** Interpreter blocks only, when paired: index of the source block in this array. */
  source_index?: number;
}

export interface Evaluation {
  id: string;
  session_id: string;
  transcript: TranscriptSegment[] | null;
  aligned_blocks: AlignedBlock[] | null;
  interpreter_speaker: string | null;
  client_speaker: string | null;
  overall_score: number | null;
  accuracy_score: number | null;
  completeness_score: number | null;
  terminology_score: number | null;
  fluency_score: number | null;
  semantic_similarity_scores: number[] | null;
  client_translations: string[] | null;
  llm_feedback: string | null;
  structured_issues: PairIssues[] | null;
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

export interface Me {
  id: string;
  email: string;
}
