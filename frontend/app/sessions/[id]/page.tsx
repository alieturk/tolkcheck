"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { confirmRoles, getEvaluation, getSession } from "../../../lib/api";
import { getErrorMessage } from "../../../lib/errors";
import type { Evaluation, Session, SessionStatus } from "../../../lib/types";

// ── Stepper config ─────────────────────────────────────────────────────────

const STEPS: { label: string; statuses: SessionStatus[] }[] = [
  { label: "Uploaden",                  statuses: ["pending"] },
  { label: "Transcriberen",             statuses: ["transcribing"] },
  { label: "Sprekers identificeren",    statuses: ["diarising"] },
  { label: "Rollen bevestigen",         statuses: ["awaiting_role_confirmation"] },
  { label: "Beoordelen",                statuses: ["scoring"] },
  { label: "Feedback genereren",        statuses: ["generating"] },
  { label: "Voltooid",                  statuses: ["completed"] },
];

function getStepIndex(status: SessionStatus): number {
  return STEPS.findIndex((s) => s.statuses.includes(status));
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Stepper({ status }: { status: SessionStatus }) {
  const current = getStepIndex(status);
  return (
    <ol className="flex items-center gap-0 w-full">
      {STEPS.map((step, i) => {
        const done    = i < current;
        const active  = i === current;
        const last    = i === STEPS.length - 1;
        return (
          <li key={step.label} className="flex items-center flex-1">
            <div className="flex flex-col items-center gap-1 flex-1">
              <div
                className={`
                  w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold border-2 transition-colors
                  ${done   ? "bg-blue-600 border-blue-600 text-white"   : ""}
                  ${active ? "border-blue-600 text-blue-600 bg-white animate-pulse" : ""}
                  ${!done && !active ? "border-gray-300 text-gray-400 bg-white" : ""}
                `}
              >
                {done ? (
                  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
                  </svg>
                ) : (
                  <span>{i + 1}</span>
                )}
              </div>
              <span className={`text-[10px] text-center leading-tight hidden sm:block ${active ? "text-blue-600 font-medium" : done ? "text-gray-600" : "text-gray-400"}`}>
                {step.label}
              </span>
            </div>
            {!last && (
              <div className={`h-0.5 flex-1 mx-1 transition-colors ${done ? "bg-blue-600" : "bg-gray-200"}`} />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function SpinnerIcon() {
  return (
    <svg className="animate-spin w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  );
}

// ── Role confirmation ──────────────────────────────────────────────────────

interface RoleConfirmationProps {
  sessionId: string;
  evaluation: Evaluation;
  onConfirmed: () => void;
}

function RoleConfirmation({ sessionId, evaluation, onConfirmed }: RoleConfirmationProps) {
  const segments = evaluation.transcript ?? [];
  const preview  = segments.slice(0, 10);
  const speakers = [...new Set(segments.map((s) => s.speaker))].sort();

  const [interpreter, setInterpreter] = useState(speakers[0] ?? "");
  const [client,      setClient]      = useState(speakers[1] ?? speakers[0] ?? "");
  const [saving,      setSaving]      = useState(false);
  const [error,       setError]       = useState<string | null>(null);

  async function handleConfirm() {
    if (!interpreter || !client) return;
    setSaving(true);
    setError(null);
    try {
      await confirmRoles(sessionId, interpreter, client);
      onConfirmed();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fout bij bevestigen. Probeer het opnieuw.");
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Bevestig sprekers</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Bekijk de eerste fragmenten en wijs aan welke spreker de tolk is en welke de cliënt.
        </p>
      </div>

      {/* Transcript preview */}
      <div className="rounded-xl border border-gray-200 bg-gray-50 divide-y divide-gray-100 max-h-64 overflow-y-auto">
        {preview.map((seg, i) => (
          <div key={i} className="flex gap-3 px-4 py-2.5">
            <span className="shrink-0 text-xs font-mono text-gray-400 w-10 pt-0.5">
              {formatTime(seg.start)}
            </span>
            <span className="shrink-0 rounded px-1.5 py-0.5 text-xs font-medium bg-gray-200 text-gray-700 self-start">
              {seg.speaker}
            </span>
            <p className="text-sm text-gray-800 leading-relaxed">{seg.text}</p>
          </div>
        ))}
        {segments.length === 0 && (
          <p className="px-4 py-4 text-sm text-gray-400 text-center">Geen transcriptfragmenten beschikbaar.</p>
        )}
      </div>

      {/* Speaker dropdowns */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Welke spreker is de tolk?
          </label>
          <select
            value={interpreter}
            onChange={(e) => setInterpreter(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {speakers.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Welke spreker is de cliënt?
          </label>
          <select
            value={client}
            onChange={(e) => setClient(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {speakers.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      {interpreter === client && (
        <p className="text-xs text-amber-600">
          Tolk en cliënt zijn dezelfde spreker. Selecteer twee verschillende sprekers.
        </p>
      )}

      {error && (
        <p className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <button
        onClick={handleConfirm}
        disabled={saving || !interpreter || !client || interpreter === client}
        className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white
                   hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {saving ? "Bevestigen..." : "Rollen bevestigen en doorgaan"}
      </button>
    </div>
  );
}

// ── Evaluation results ─────────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const color = score >= 80 ? "text-green-600" : score >= 60 ? "text-amber-500" : "text-red-500";
  return (
    <span className={`text-2xl font-bold tabular-nums ${color}`}>{score.toFixed(1)}</span>
  );
}

function EvaluationResults({ evaluation, session }: { evaluation: Evaluation; session: Session }) {
  const scores = [
    { label: "Overall",       value: evaluation.overall_score },
    { label: "Nauwkeurigheid", value: evaluation.accuracy_score },
    { label: "Volledigheid",  value: evaluation.completeness_score },
    { label: "Terminologie",  value: evaluation.terminology_score },
    { label: "Vloeiendheid",  value: evaluation.fluency_score },
  ];

  const interp = evaluation.interpreter_speaker;

  return (
    <div className="space-y-6">
      {/* Score grid */}
      <div>
        <h2 className="text-base font-semibold text-gray-900 mb-3">Beoordelingsscores</h2>
        <div className="grid grid-cols-5 gap-3">
          {scores.map(({ label, value }) => (
            <div key={label} className="flex flex-col items-center rounded-xl border border-gray-200 bg-white p-3 gap-1">
              {value != null ? <ScoreRing score={value} /> : <span className="text-gray-400 text-sm">—</span>}
              <span className="text-xs text-gray-500 text-center">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* LLM feedback */}
      {evaluation.llm_feedback && (
        <div>
          <h2 className="text-base font-semibold text-gray-900 mb-3">Feedback</h2>
          <div className="relative rounded-xl border border-gray-200 bg-gray-50 p-4">
            <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">
              {evaluation.llm_feedback}
            </pre>
            <button
              onClick={() => navigator.clipboard.writeText(evaluation.llm_feedback!)}
              className="absolute top-3 right-3 rounded-md bg-white border border-gray-200 px-2 py-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              Kopieer
            </button>
          </div>
        </div>
      )}

      {/* Transcript */}
      {evaluation.transcript && evaluation.transcript.length > 0 && (
        <div>
          <h2 className="text-base font-semibold text-gray-900 mb-3">Transcriptie</h2>
          <div className="rounded-xl border border-gray-200 bg-gray-50 divide-y divide-gray-100 max-h-96 overflow-y-auto">
            {evaluation.transcript.map((seg, i) => {
              const isInterp = seg.speaker === interp;
              return (
                <div key={i} className="flex gap-3 px-4 py-2.5">
                  <span className="shrink-0 text-xs font-mono text-gray-400 w-10 pt-0.5">
                    {formatTime(seg.start)}
                  </span>
                  <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium self-start
                    ${isInterp ? "bg-blue-100 text-blue-700" : "bg-orange-100 text-orange-700"}`}>
                    {isInterp ? "Tolk" : "Cliënt"}
                  </span>
                  <p className="text-sm text-gray-800 leading-relaxed">{seg.text}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Utility ────────────────────────────────────────────────────────────────

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ── Page ───────────────────────────────────────────────────────────────────

const PROCESSING_STATUSES: SessionStatus[] = [
  "pending", "transcribing", "diarising", "scoring", "generating",
];

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();

  const [session,    setSession]    = useState<Session | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [loadError,  setLoadError]  = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchEvaluation = useCallback(async (sessionId: string) => {
    try {
      const ev = await getEvaluation(sessionId);
      setEvaluation(ev);
    } catch {
      // Evaluation row may not exist yet — ignore
    }
  }, []);

  const fetchSession = useCallback(async () => {
    try {
      const s = await getSession(id);
      setSession(s);

      if (
        s.status === "awaiting_role_confirmation" ||
        s.status === "completed"
      ) {
        await fetchEvaluation(id);
      }
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Kon sessie niet laden.");
    }
  }, [id, fetchEvaluation]);

  useEffect(() => {
    fetchSession();
    pollRef.current = setInterval(fetchSession, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchSession]);

  // Stop polling when terminal state reached
  useEffect(() => {
    if (!session) return;
    if (session.status === "completed" || session.status === "failed") {
      if (pollRef.current) clearInterval(pollRef.current);
    }
  }, [session]);

  if (loadError) {
    return (
      <main className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 max-w-md w-full text-center">
          <p className="text-red-600 text-sm">{loadError}</p>
          <Link href="/" className="mt-4 inline-block text-sm text-blue-600 hover:underline">
            Terug naar overzicht
          </Link>
        </div>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="min-h-screen bg-gray-50 flex items-center justify-center">
        <SpinnerIcon />
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">{session.filename}</h1>
            <p className="text-xs text-gray-400 mt-0.5">
              {session.ind_case_id ? `Zaaknummer: ${session.ind_case_id} · ` : ""}
              {new Date(session.created_at).toLocaleDateString("nl-NL", {
                day: "numeric", month: "long", year: "numeric",
              })}
            </p>
          </div>
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-700">
            ← Overzicht
          </Link>
        </div>

        {/* Stepper card */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
          <Stepper status={session.status} />

          {/* In-progress indicator */}
          {PROCESSING_STATUSES.includes(session.status) && (
            <div className="mt-6 flex items-center gap-2 text-sm text-gray-500">
              <SpinnerIcon />
              <span>
                {session.status === "pending"       && "Wachten op verwerking..."}
                {session.status === "transcribing"  && "Audio wordt getranscribeerd..."}
                {session.status === "diarising"     && "Sprekers worden geïdentificeerd..."}
                {session.status === "scoring"       && "Kwaliteit wordt berekend..."}
                {session.status === "generating"    && "Feedback wordt gegenereerd..."}
              </span>
            </div>
          )}
        </div>

        {/* Role confirmation */}
        {session.status === "awaiting_role_confirmation" && evaluation && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
            <RoleConfirmation
              sessionId={id}
              evaluation={evaluation}
              onConfirmed={fetchSession}
            />
          </div>
        )}

        {/* Error state */}
        {session.status === "failed" && (
          <div className="bg-white rounded-2xl shadow-sm border border-red-200 p-6">
            <h2 className="text-base font-semibold text-red-700 mb-1">Evaluatie mislukt</h2>
            <p className="text-sm text-gray-700">{getErrorMessage(session.error_code)}</p>
            <Link
              href="/upload"
              className="mt-4 inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
            >
              Nieuwe evaluatie starten
            </Link>
          </div>
        )}

        {/* Completed results */}
        {session.status === "completed" && evaluation && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
            <EvaluationResults evaluation={evaluation} session={session} />
          </div>
        )}
      </div>
    </main>
  );
}
