export const ERROR_MESSAGES: Record<string, string> = {
  UNSUPPORTED_FORMAT:    "Audioformaat niet ondersteund. Upload een mp3, wav of mp4.",
  TRANSCRIPTION_FAILED:  "Transcriptie mislukt. Controleer de audiokwaliteit.",
  DIARISATION_FAILED:    "Sprekeridentificatie mislukt. Controleer de audiokwaliteit.",
  SCORING_FAILED:        "Beoordelingsberekening mislukt. Probeer het opnieuw.",
  LLM_ERROR:             "Feedbackgeneratie mislukt. Probeer het opnieuw.",
};

export function getErrorMessage(code: string | null): string {
  if (!code) return "Er is een onbekende fout opgetreden. Probeer het opnieuw.";
  return ERROR_MESSAGES[code] ?? `Er is een fout opgetreden (${code}). Probeer het opnieuw.`;
}
