"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { uploadSession } from "../../lib/api";

const LANGUAGES = [
  { code: "nl", label: "Nederlands" },
  { code: "ar", label: "Arabisch" },
  { code: "tr", label: "Turks" },
  { code: "fa", label: "Dari / Farsi" },
  { code: "so", label: "Somalisch" },
  { code: "ti", label: "Tigrinya" },
];

const ACCEPTED_TYPES = [
  "audio/mpeg",
  "audio/wav",
  "audio/x-wav",
  "audio/mp4",
  "audio/ogg",
  "audio/webm",
  "video/mp4",
];

const MAX_SIZE_MB = 500;
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

export default function UploadPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("nl");
  const [caseId, setCaseId] = useState("");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  function validateFile(f: File): string | null {
    if (!ACCEPTED_TYPES.includes(f.type)) {
      return `Bestandstype '${f.type}' wordt niet ondersteund. Upload een mp3, wav, mp4, ogg of webm.`;
    }
    if (f.size > MAX_SIZE_BYTES) {
      return `Bestand is groter dan ${MAX_SIZE_MB} MB.`;
    }
    return null;
  }

  function pickFile(f: File) {
    const err = validateFile(f);
    if (err) {
      setError(err);
      setFile(null);
    } else {
      setError(null);
      setFile(f);
    }
  }

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;

    setUploading(true);
    setError(null);
    try {
      const res = await uploadSession(file, language, caseId || undefined);
      router.push(`/sessions/${res.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload mislukt. Probeer het opnieuw.");
      setUploading(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
        <h1 className="text-2xl font-semibold text-gray-900 mb-1">Nieuwe evaluatie</h1>
        <p className="text-sm text-gray-500 mb-6">
          Upload een audio-opname van een IND-tolkgesprek om de kwaliteit te evalueren.
        </p>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Drop zone */}
          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`
              flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed
              px-6 py-10 cursor-pointer transition-colors
              ${dragging ? "border-blue-500 bg-blue-50" : "border-gray-300 hover:border-gray-400 bg-gray-50"}
            `}
          >
            <svg className="w-8 h-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            {file ? (
              <p className="text-sm font-medium text-gray-700">{file.name}</p>
            ) : (
              <>
                <p className="text-sm font-medium text-gray-700">
                  Sleep een audiobestand hierheen of klik om te kiezen
                </p>
                <p className="text-xs text-gray-400">mp3, wav, mp4, ogg, webm — max {MAX_SIZE_MB} MB</p>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="audio/*,video/mp4"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) pickFile(f);
              }}
            />
          </div>

          {/* Language select */}
          <div>
            <label htmlFor="language" className="block text-sm font-medium text-gray-700 mb-1">
              Taal van de cliënt
            </label>
            <div className="relative">
              <select
                id="language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm
                           focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 appearance-none"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-gray-400">
                <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
                </svg>
              </span>
            </div>
            {language === "ti" && (
              <p className="mt-1 text-xs text-amber-600">
                Tigrinya heeft lagere Whisper-nauwkeurigheid. Controleer de transcriptie extra zorgvuldig.
              </p>
            )}
          </div>

          {/* Case ID */}
          <div>
            <label htmlFor="case_id" className="block text-sm font-medium text-gray-700 mb-1">
              IND-zaaknummer <span className="text-gray-400 font-normal">(optioneel)</span>
            </label>
            <input
              id="case_id"
              type="text"
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              placeholder="bijv. IND-2024-00123"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm
                         focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={!file || uploading}
            className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white
                       hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {uploading ? "Uploaden..." : "Evaluatie starten"}
          </button>
        </form>
      </div>
    </main>
  );
}
