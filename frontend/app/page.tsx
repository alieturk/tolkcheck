"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listSessions } from "../lib/api";
import type { Session, SessionStatus } from "../lib/types";

// ── Status badge ───────────────────────────────────────────────────────────

const STATUS_LABELS: Record<SessionStatus, string> = {
  pending:                    "In wachtrij",
  transcribing:               "Transcriberen",
  diarising:                  "Sprekers",
  awaiting_role_confirmation: "Rollen bevestigen",
  scoring:                    "Beoordelen",
  generating:                 "Feedback",
  completed:                  "Voltooid",
  failed:                     "Mislukt",
};

const STATUS_COLORS: Record<SessionStatus, string> = {
  pending:                    "bg-gray-100 text-gray-600",
  transcribing:               "bg-blue-100 text-blue-700",
  diarising:                  "bg-blue-100 text-blue-700",
  awaiting_role_confirmation: "bg-amber-100 text-amber-700",
  scoring:                    "bg-blue-100 text-blue-700",
  generating:                 "bg-blue-100 text-blue-700",
  completed:                  "bg-green-100 text-green-700",
  failed:                     "bg-red-100 text-red-700",
};

function StatusBadge({ status }: { status: SessionStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[status]}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    listSessions()
      .then(setSessions)
      .catch((err) => setError(err instanceof Error ? err.message : "Kon sessies niet laden."));
  }, []);

  return (
    <main className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Tolkcheck</h1>
          <p className="text-xs text-gray-400">AI-kwaliteitsevaluatie voor IND-tolkgesprekken</p>
        </div>
        <Link
          href="/upload"
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
        >
          Nieuwe evaluatie
        </Link>
      </header>

      <div className="max-w-5xl mx-auto px-6 py-8">
        {error && (
          <p className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-6">
            {error}
          </p>
        )}

        {sessions === null && !error && (
          <div className="flex items-center justify-center py-20">
            <svg className="animate-spin w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          </div>
        )}

        {sessions?.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 gap-4 text-center">
            <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center">
              <svg className="w-8 h-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <p className="font-medium text-gray-900">Nog geen evaluaties</p>
              <p className="text-sm text-gray-500 mt-1">Upload een audio-opname om te beginnen.</p>
            </div>
            <Link
              href="/upload"
              className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
            >
              Eerste evaluatie starten
            </Link>
          </div>
        )}

        {sessions && sessions.length > 0 && (
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left px-5 py-3.5 text-xs font-medium text-gray-500 uppercase tracking-wide">Bestandsnaam</th>
                  <th className="text-left px-5 py-3.5 text-xs font-medium text-gray-500 uppercase tracking-wide">Taal</th>
                  <th className="text-left px-5 py-3.5 text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="text-left px-5 py-3.5 text-xs font-medium text-gray-500 uppercase tracking-wide">Aangemaakt</th>
                  <th className="px-5 py-3.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {sessions.map((s) => (
                  <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-5 py-3.5 font-medium text-gray-900 max-w-xs truncate">
                      {s.filename}
                      {s.ind_case_id && (
                        <span className="ml-2 text-xs text-gray-400 font-normal">{s.ind_case_id}</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-gray-600 uppercase text-xs">{s.language}</td>
                    <td className="px-5 py-3.5"><StatusBadge status={s.status} /></td>
                    <td className="px-5 py-3.5 text-gray-400 text-xs whitespace-nowrap">
                      {new Date(s.created_at).toLocaleDateString("nl-NL", {
                        day: "numeric", month: "short", year: "numeric",
                      })}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <Link
                        href={`/sessions/${s.id}`}
                        className="text-blue-600 hover:text-blue-800 text-xs font-medium"
                      >
                        Bekijken →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
