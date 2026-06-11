"use client";

import { useState } from "react";
import type { Evaluation, IssueItem } from "../../../lib/types";

// Icon components (emoji fallbacks — accept className so JSX props compile)
const AlertTriangle = ({ className: _ }: { className?: string }) => <span>⚠️</span>;
const CheckCircle   = ({ className: _ }: { className?: string }) => <span>✓</span>;
const ChevronDown   = ({ className: _ }: { className?: string }) => <span>▼</span>;
const ChevronUp     = ({ className: _ }: { className?: string }) => <span>▲</span>;
const Flag          = ({ className: _ }: { className?: string }) => <span>🚩</span>;
const ThumbsDown    = ({ className: _ }: { className?: string }) => <span>👎</span>;
const ThumbsUp      = ({ className: _ }: { className?: string }) => <span>👍</span>;

// ── Constants ──────────────────────────────────────────────────────────────

const severityColors: Record<string, string> = {
  critical: "bg-red-50 border-red-300 text-red-900",
  high:     "bg-orange-50 border-orange-300 text-orange-900",
  medium:   "bg-yellow-50 border-yellow-300 text-yellow-900",
  low:      "bg-blue-50 border-blue-300 text-blue-900",
};

const severityLabels: Record<string, string> = {
  critical: "Kritiek",
  high:     "Hoog",
  medium:   "Gemiddeld",
  low:      "Laag",
};

const issueTypeLabels: Record<string, string> = {
  omission:       "Omissie",
  addition:       "Toevoeging",
  mistranslation: "Verkeerde vertaling",
  "false-negative": "Vals alarm",
};

// ── Types ──────────────────────────────────────────────────────────────────

type SpeakerRole = "client" | "interpreter" | "interviewer";

interface DisplaySegment {
  id: string;
  startTime: string;
  endTime: string;
  speaker: SpeakerRole;
  originalText: string;
  detectedLanguage?: string;  // actual language Whisper detected for this turn
  machineTranslation?: string; // Dutch machine translation of client speech
  translatedText?: string;     // what the interpreter actually said in Dutch
  accuracy?: number;   // 0–1 LaBSE score
  issues?: IssueItem[];
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function accuracyColor(a: number): string {
  if (a >= 0.9) return "bg-green-100 text-green-800";
  if (a >= 0.7) return "bg-yellow-100 text-yellow-800";
  if (a >= 0.5) return "bg-orange-100 text-orange-800";
  return "bg-red-100 text-red-800";
}

// Re-implement _align_turns to build display-ready segments from raw transcript.
// Groups consecutive same-speaker raw segments into turns, then for each client
// turn finds the next interpreter turn as the translation.
function buildDisplaySegments(evaluation: Evaluation): DisplaySegment[] {
  const raw = evaluation.transcript ?? [];
  const interpSpeaker = evaluation.interpreter_speaker;
  const clientSpeaker = evaluation.client_speaker;
  const scores = evaluation.semantic_similarity_scores ?? [];
  const translations = evaluation.client_translations ?? [];
  const issuePairs = evaluation.structured_issues ?? [];

  // Build issue map: pair_index → IssueItem[]
  const issueMap = new Map<number, IssueItem[]>();
  for (const p of issuePairs) {
    issueMap.set(p.pair_index, p.issues ?? []);
  }

  // Group raw segments into turns; keep the first segment's detected language
  const turns: {
    speaker: string;
    role: SpeakerRole;
    start: number;
    end: number;
    text: string;
    language?: string;
  }[] = [];

  for (const seg of raw) {
    const role: SpeakerRole =
      seg.speaker === interpSpeaker
        ? "interpreter"
        : seg.speaker === clientSpeaker
        ? "client"
        : "interviewer";

    if (turns.length > 0 && turns[turns.length - 1].speaker === seg.speaker) {
      turns[turns.length - 1].text += " " + seg.text;
      turns[turns.length - 1].end = seg.end;
    } else {
      turns.push({ speaker: seg.speaker, role, start: seg.start, end: seg.end, text: seg.text, language: seg.language });
    }
  }

  // Block-level pairing: mirrors _align_blocks in the backend.
  // For each client block, collect ALL following interpreter turns (until the next
  // client block) into one translatedText. This prevents the same short source
  // fragment from being compared against many different interpreter segments.
  const display: DisplaySegment[] = [];
  let pairIndex = 0;

  for (let i = 0; i < turns.length; i++) {
    const turn = turns[i];

    if (turn.role === "interpreter") {
      // Absorbed into the preceding client block's translatedText below.
      continue;
    }

    if (turn.role === "client") {
      // Collect ALL following interpreter turns until the next client turn.
      const interpParts: string[] = [];
      for (let j = i + 1; j < turns.length; j++) {
        if (turns[j].role === "client") break;
        if (turns[j].role === "interpreter") interpParts.push(turns[j].text);
      }
      const translatedText = interpParts.length > 0 ? interpParts.join(" ") : undefined;

      const idx = pairIndex++;
      display.push({
        id: String(i),
        startTime: fmtTime(turn.start),
        endTime:   fmtTime(turn.end),
        speaker:   "client",
        originalText: turn.text,
        detectedLanguage: turn.language,
        machineTranslation: translations[idx],
        translatedText,
        accuracy: scores[idx] !== undefined ? scores[idx] : undefined,
        issues: issueMap.get(idx),
      });
    } else {
      // IND officer turn — standalone row.
      display.push({
        id: String(i),
        startTime:    fmtTime(turn.start),
        endTime:      fmtTime(turn.end),
        speaker:      "interviewer",
        originalText: turn.text,
      });
    }
  }

  return display;
}

// ── TimeSegment ─────────────────────────────────────────────────────────────

interface TimeSegmentProps {
  segment: DisplaySegment;
  isExpanded: boolean;
  onToggle: () => void;
  feedback?: "correct" | "incorrect";
  onFeedback: (f: "correct" | "incorrect") => void;
}

function TimeSegment({ segment, isExpanded, onToggle, feedback, onFeedback }: TimeSegmentProps) {
  const realIssues = segment.issues?.filter((i) => i.type !== "false-negative") ?? [];
  const hasCritical = realIssues.some((i) => i.severity === "critical");
  const hasHigh     = realIssues.some((i) => i.severity === "high");
  const hasIssues   = realIssues.length > 0;

  const speakerLabel =
    segment.speaker === "client"
      ? "Cliënt"
      : segment.speaker === "interpreter"
      ? "Tolk"
      : "IND-medewerker";

  const borderClass = hasCritical
    ? "border-red-300 bg-red-50/30"
    : hasHigh
    ? "border-orange-300 bg-orange-50/30"
    : hasIssues
    ? "border-yellow-300 bg-yellow-50/30"
    : "border-gray-200";

  return (
    <div className={`border rounded-lg overflow-hidden transition-all ${borderClass}`}>
      <div
        className="p-4 cursor-pointer hover:bg-gray-50/50 transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            {/* Meta row */}
            <div className="flex items-center gap-3 mb-2 flex-wrap">
              <span className="text-sm px-2 py-0.5 bg-gray-100 rounded font-mono">
                {segment.startTime} – {segment.endTime}
              </span>
              <span className="text-sm text-gray-600">{speakerLabel}</span>

              {segment.accuracy !== undefined && (
                <span className={`text-xs px-2 py-0.5 rounded ${accuracyColor(segment.accuracy)}`}>
                  {Math.round(segment.accuracy * 100)}% nauwkeurigheid
                </span>
              )}
              {hasCritical && (
                <span className="flex items-center gap-1 text-xs text-red-600">
                  <AlertTriangle className="w-3 h-3" /> Kritiek
                </span>
              )}
              {!hasCritical && hasHigh && (
                <span className="flex items-center gap-1 text-xs text-orange-600">
                  <AlertTriangle className="w-3 h-3" /> Hoog
                </span>
              )}
            </div>

            {/* Text */}
            <div className="space-y-2">
              {segment.speaker === "client" && (
                <>
                  <div>
                    <p className="text-xs text-gray-500 mb-1">
                      Origineel ({segment.detectedLanguage?.toUpperCase() ?? "?"}):
                    </p>
                    <p className="text-sm text-gray-900 leading-relaxed">{segment.originalText}</p>
                  </div>
                  {segment.machineTranslation && (
                    <div className="pl-3 border-l-2 border-blue-200">
                      <p className="text-xs text-blue-500 mb-1">Automatische vertaling (NL):</p>
                      <p className="text-sm text-gray-700 leading-relaxed italic">{segment.machineTranslation}</p>
                    </div>
                  )}
                  {segment.translatedText && (
                    <div>
                      <p className="text-xs text-gray-500 mb-1">Vertaling tolk (NL):</p>
                      <p className="text-sm text-gray-900 leading-relaxed">{segment.translatedText}</p>
                    </div>
                  )}
                </>
              )}
              {segment.speaker !== "client" && (
                <p className="text-sm text-gray-900 leading-relaxed">{segment.originalText}</p>
              )}
            </div>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2 shrink-0">
            {hasIssues && (
              <span className="text-xs text-gray-500">
                {realIssues.length} {realIssues.length === 1 ? "probleem" : "problemen"}
              </span>
            )}
            {isExpanded ? (
              <ChevronUp className="w-5 h-5 text-gray-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-gray-400" />
            )}
          </div>
        </div>
      </div>

      {/* Expanded: issues + feedback */}
      {isExpanded && segment.issues && segment.issues.length > 0 && (
        <div className="border-t border-gray-200 bg-white p-4 space-y-4">
          <div>
            <h4 className="text-sm font-medium mb-3">AI-gedetecteerde problemen:</h4>
            <div className="space-y-3">
              {segment.issues.map((issue, idx) => (
                <div
                  key={idx}
                  className={`border rounded-lg p-3 ${severityColors[issue.severity] ?? "border-gray-200"}`}
                >
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs px-2 py-0.5 bg-white/60 rounded">
                        {issueTypeLabels[issue.type] ?? issue.type}
                      </span>
                      <span className="text-xs px-2 py-0.5 bg-white/60 rounded">
                        {severityLabels[issue.severity] ?? issue.severity}
                      </span>
                    </div>
                    {issue.type === "false-negative" && (
                      <CheckCircle className="w-4 h-4 shrink-0" />
                    )}
                  </div>

                  <p className="text-sm mb-2">{issue.description}</p>

                  {issue.originalPhrase && issue.originalPhrase !== "" && (
                    <div className="grid grid-cols-2 gap-3 mt-2 text-xs">
                      <div className="bg-white/60 rounded p-2">
                        <p className="text-gray-600 mb-1">Originele tekst:</p>
                        <p className="text-gray-900">{issue.originalPhrase}</p>
                      </div>
                      <div className="bg-white/60 rounded p-2">
                        <p className="text-gray-600 mb-1">Vertaald als:</p>
                        <p className="text-gray-900">{issue.translatedPhrase}</p>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="border-t pt-4">
            <p className="text-sm mb-3">Is deze AI-analyse correct?</p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => onFeedback("correct")}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors
                  ${feedback === "correct"
                    ? "border-green-600 bg-green-600 text-white"
                    : "border-green-600 text-green-700 hover:bg-green-50"}`}
              >
                <ThumbsUp className="w-4 h-4" /> Correct
              </button>
              <button
                onClick={() => onFeedback("incorrect")}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors
                  ${feedback === "incorrect"
                    ? "border-red-600 bg-red-600 text-white"
                    : "border-red-600 text-red-700 hover:bg-red-50"}`}
              >
                <ThumbsDown className="w-4 h-4" /> Incorrect
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── EvaluationView ─────────────────────────────────────────────────────────

interface Props {
  evaluation: Evaluation;
}

export default function EvaluationView({ evaluation }: Props) {
  const [activeTab, setActiveTab]       = useState(0);
  const [expandedId, setExpandedId]     = useState<string | null>(null);
  const [feedbackMap, setFeedbackMap]   = useState<Record<string, "correct" | "incorrect">>({});

  const segments = buildDisplaySegments(evaluation);

  const criticalSegs = segments.filter((s) =>
    s.issues?.some((i) => i.severity === "critical" && i.type !== "false-negative")
  );
  const highSegs = segments.filter(
    (s) =>
      s.issues?.some((i) => i.severity === "high" && i.type !== "false-negative") &&
      !s.issues?.some((i) => i.severity === "critical" && i.type !== "false-negative")
  );

  const overallScore = evaluation.overall_score ?? 0;
  const statusLabel =
    overallScore >= 80
      ? "Goed"
      : overallScore >= 60
      ? "Voldoende"
      : "Controle vereist";
  const statusColor =
    overallScore >= 80 ? "text-green-600" : overallScore >= 60 ? "text-amber-500" : "text-red-500";

  // Circular progress ring (r=28, circumference ≈ 175.9)
  const r = 28;
  const circ = 2 * Math.PI * r;
  const dash = circ * (1 - overallScore / 100);
  const ringColor =
    overallScore >= 80 ? "text-green-500" : overallScore >= 60 ? "text-amber-500" : "text-red-500";

  const tabs = [
    { label: `Alle segmenten (${segments.length})` },
    { label: `Kritieke problemen (${criticalSegs.length})`, count: criticalSegs.length },
    { label: `Hoge prioriteit (${highSegs.length})` },
  ];

  const tabSegments = [segments, criticalSegs, highSegs];

  function toggle(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  function handleFeedback(id: string, fb: "correct" | "incorrect") {
    setFeedbackMap((prev) => ({ ...prev, [id]: fb }));
  }

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        {/* Card 1: critical issues */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm text-gray-500 mb-1">Kritieke problemen</p>
              <p className="text-3xl font-bold text-gray-900">{criticalSegs.length}</p>
              <p className="text-sm text-red-600 mt-2">
                {criticalSegs.length === 0 ? "Geen kritieke problemen" : "Directe aandacht vereist"}
              </p>
            </div>
            <AlertTriangle
              className={`w-8 h-8 ${criticalSegs.length > 0 ? "text-red-500" : "text-gray-300"}`}
            />
          </div>
        </div>

        {/* Card 2: average accuracy */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm text-gray-500 mb-1">Gemiddelde nauwkeurigheid</p>
              <p className={`text-3xl font-bold ${statusColor}`}>{overallScore.toFixed(1)}%</p>
              <p className={`text-sm mt-2 ${statusColor}`}>{statusLabel}</p>
            </div>
            <svg className={`-rotate-90 w-16 h-16 ${ringColor}`} viewBox="0 0 64 64">
              <circle cx="32" cy="32" r={r} stroke="currentColor" strokeWidth="6" fill="transparent" className="text-gray-200" />
              <circle
                cx="32" cy="32" r={r}
                stroke="currentColor" strokeWidth="6" fill="transparent"
                strokeDasharray={circ}
                strokeDashoffset={dash}
              />
            </svg>
          </div>
        </div>

        {/* Card 3: status */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm text-gray-500 mb-1">Status controle</p>
              <p className={`text-xl font-semibold mt-1 ${statusColor}`}>{statusLabel}</p>
              <p className="text-sm text-gray-500 mt-2">
                {criticalSegs.length > 0
                  ? `${criticalSegs.length} kritieke segment(en)`
                  : "Geen kritieke omissies"}
              </p>
            </div>
            <Flag className={`w-8 h-8 ${overallScore < 60 ? "text-orange-500" : overallScore < 80 ? "text-amber-400" : "text-green-500"}`} />
          </div>
        </div>
      </div>

      {/* LLM overall feedback */}
      {evaluation.llm_feedback && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-base font-semibold text-gray-900 mb-3">Samenvattende feedback</h2>
          <div className="relative">
            <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">
              {evaluation.llm_feedback}
            </pre>
            <button
              onClick={() => navigator.clipboard.writeText(evaluation.llm_feedback!)}
              className="absolute top-0 right-0 rounded-md bg-white border border-gray-200 px-2 py-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              Kopieer
            </button>
          </div>
        </div>
      )}

      {/* Segment tabs */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {/* Tab bar */}
        <div className="flex border-b border-gray-200">
          {tabs.map((tab, i) => (
            <button
              key={i}
              onClick={() => setActiveTab(i)}
              className={`flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 transition-colors
                ${activeTab === i
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"}`}
            >
              {tab.label}
              {i === 1 && tab.count! > 0 && (
                <span className="bg-red-500 text-white text-xs px-1.5 py-0.5 rounded-full leading-none">
                  !
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="p-5 space-y-4">
          {tabSegments[activeTab].length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <CheckCircle className="w-12 h-12 mx-auto mb-3 text-green-500" />
              <p>Geen problemen in deze categorie</p>
            </div>
          ) : (
            tabSegments[activeTab].map((seg) => (
              <TimeSegment
                key={seg.id}
                segment={seg}
                isExpanded={expandedId === seg.id}
                onToggle={() => toggle(seg.id)}
                feedback={feedbackMap[seg.id]}
                onFeedback={(fb) => handleFeedback(seg.id, fb)}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
