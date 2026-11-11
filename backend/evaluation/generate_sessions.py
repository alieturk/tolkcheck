"""Generate synthetic DV4 test sessions (default: claude-haiku-5-5, prompt tolkcheck-sessies-v4).

This script only makes data. It chooses no threshold, scores nothing, and the
measurement code (sessions.py, session_lint.py, detection_check.py) is untouched:
every generated session must pass ``sessions.load_session`` and
``session_lint.lint_session`` before it is written.

What is fixed per session number n, not left to the model:

* split   — dev for 20–29 and 50–59; test for 30–49, 60–69 and 70–89
* topic   — (n − 20) mod 7, see TOPICS
* voices  — officer and applicant rotate a/b/c with n mod 3 (the rotation S20–S24
            already use); the interpreter is always vb_interp_a
* subtypes — one per deviation category, by rotation (session_lint.expected_subtypes);
            the lint checks them for prompt v3

Only errors go back to the model for a new attempt, never warnings or lint notes.

Providers: a --model starting with "gemini-" goes through google-genai with
GEMINI_API_KEY from backend/.env (same prompt as system instruction, same message,
same extraction, lint and retry rule); every other model through Anthropic with
ANTHROPIC_API_KEY. generation_log.jsonl records the provider and the provider's own
token counts (Gemini: usage_metadata). Keys are never printed or written anywhere.

    uv run python evaluation/generate_sessions.py --from 25 --to 26 --model gemini-3.8-flash \\
        --out-dir ../eval/data/tolkcheck_dv4/sessions_gemini_trial

The prompt goes in as the system prompt; each session is one user message with
session_id, split, topic and voices. The JSON is taken from the code block in the
answer. After the JSON is parsed, split, topic, voices, generator (the model id the
API reports), prompt_version, reviewed (false) and reviewed_by (null) are
overwritten. If the session fails the loader or the lint, the findings go back to
the model and it tries again, at most MAX_RETRIES times; a session that still
fails lands in <out-dir>/rejected/ with its findings.

Per session the full answer of every attempt (including the control table) is kept
in <out-dir>/raw/Sxx.md, and tokens, attempts and an estimated cost are appended to
<out-dir>/generation_log.jsonl.

    uv run python evaluation/generate_sessions.py --from 25 --to 26 --dry-run
    uv run python evaluation/generate_sessions.py --from 25 --to 26
    uv run python evaluation/generate_sessions.py --from 30 --to 49 --model claude-sonnet-4-6
    uv run python evaluation/generate_sessions.py --from 25 --to 26 --prompt evaluation/prompts/tolkcheck-sessies-v2.md

``--prompt`` picks the prompt file (default prompts/tolkcheck-sessies-v4.md); the
session's prompt_version is the file name without ``.md``.

The lint findings of a test session are not printed (they go to the rejected
folder only), so running this for test numbers shows no test content on screen.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

EVAL_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = EVAL_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
for _p in (EVAL_DIR, BACKEND_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from session_lint import DEVIATIONS, expected_subtypes, lint_session  # noqa: E402
from sessions import SessionFormatError, load_session  # noqa: E402

PROMPTS_DIR = EVAL_DIR / "prompts"
DEFAULT_PROMPT = PROMPTS_DIR / "tolkcheck-sessies-v4.md"
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_OUT_DIR = REPO_ROOT / "eval" / "data" / "tolkcheck_dv4" / "sessions_v2"
LOG_NAME = "generation_log.jsonl"

MIN_NUMBER, MAX_NUMBER = 20, 89
MAX_RETRIES = 3          # retries after the first attempt, so at most 4 calls
MAX_TOKENS = 32000

TOPICS: tuple[str, ...] = (
    "aanhouding en detentie",
    "verhoor en behandeling op het politiebureau",
    "bedreigingen na publicaties",
    "vertrek en reisroute",
    "familie en terugkeer",
    "werk en politieke activiteiten",
    "documenten en identiteit",
)
VOICE_LETTERS = ("a", "b", "c")
INTERPRETER_VOICE = "vb_interp_a"

# USD per million tokens: (input, output, cache write 5 min, cache read).
# An estimate for the log only; check the current price list before quoting it.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    # claude-haiku-5-5: $0.10 / $0.50 for prompts under 100K tokens. Nog niet
    # geverifieerd, controleer op https://www.anthropic.com/pricing (the figures come
    # from an overview site). The cache prices (1.25× and 0.1× input) are assumed.
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}
# Gemini, USD per million tokens: (input, output). Thinking tokens are billed as
# output. Cached input is counted at the full input price (an overestimate).
# The gemini-3.8-flash figures come from an overview site, NOT from Google:
# check them on https://ai.google.dev/pricing before quoting any cost.
GEMINI_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
}

ANTHROPIC, GEMINI = "anthropic", "gemini"


def provider_for(model: str) -> str:
    """Models starting with "gemini-" go through google-genai, all others through Anthropic."""
    return GEMINI if model.startswith("gemini-") else ANTHROPIC


# --------------------------------------------------------------------------- #
# What is fixed per session number
# --------------------------------------------------------------------------- #

def split_for(n: int) -> str:
    if 20 <= n <= 29 or 50 <= n <= 59:
        return "dev"
    if 30 <= n <= 49 or 60 <= n <= 89:
        return "test"
    raise ValueError(f"sessienummer {n} valt buiten {MIN_NUMBER}–{MAX_NUMBER}")


def topic_for(n: int) -> str:
    return TOPICS[(n - 20) % len(TOPICS)]


def voices_for(n: int) -> dict[str, str]:
    """Officer and applicant rotate with n mod 3, in the order S20–S24 use:
    n mod 3 = 2 → officer a / applicant b, 0 → b / c, 1 → c / a."""
    return {
        "officer": f"vb_officer_{VOICE_LETTERS[(n + 1) % 3]}",
        "applicant": f"vb_applicant_{VOICE_LETTERS[(n + 2) % 3]}",
        "interpreter": INTERPRETER_VOICE,
    }


@dataclass(frozen=True)
class Assignment:
    number: int
    session_id: str
    split: str
    topic: str
    voices: dict[str, str]
    subtypes: dict[str, str]


def assignment(n: int) -> Assignment:
    split = split_for(n)  # raises for numbers outside the range
    return Assignment(n, f"S{n}", split, topic_for(n), voices_for(n), expected_subtypes(n))


def user_message(a: Assignment) -> str:
    spec = {"session_id": a.session_id, "split": a.split, "topic": a.topic, "voices": a.voices,
            "subtypes": a.subtypes}
    return ("Maak deze sessie volgens de instructies. Gebruik voor elke afwijking precies het "
            "subtype dat hieronder bij de categorie staat; kies zelf geen ander subtype.\n\n```json\n"
            + json.dumps(spec, indent=1, ensure_ascii=False) + "\n```")


# --------------------------------------------------------------------------- #
# Answer → session
# --------------------------------------------------------------------------- #

class ExtractError(ValueError):
    """No usable session JSON in the model's answer."""


_FENCE = re.compile(r"```([A-Za-z0-9_-]*)[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Return the session object from the fenced code block in ``text``.

    Blocks tagged ``json`` are tried before untagged ones. The session is the
    block that parses to an object with a ``pairs`` list; more than one such
    block is an error rather than a guess."""
    blocks = _FENCE.findall(text)
    if not blocks:
        raise ExtractError("geen codeblok (```json ... ```) in het antwoord")
    candidates, problems = [], []
    for tag, body in sorted(blocks, key=lambda b: b[0].lower() != "json"):
        if tag and tag.lower() != "json":
            continue
        try:
            obj = json.loads(body)
        except json.JSONDecodeError as exc:
            problems.append(f"codeblok is geen geldige JSON: {exc}")
            continue
        if isinstance(obj, dict) and isinstance(obj.get("pairs"), list):
            candidates.append(obj)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ExtractError(f"{len(candidates)} codeblokken met een sessie; verwacht er één")
    raise ExtractError("; ".join(problems) or "geen codeblok met een JSON-object met 'pairs'")


def prompt_version_of(path: Path) -> str:
    """The prompt version is the prompt's file name without extension."""
    return Path(path).stem


def apply_overrides(data: dict, a: Assignment, model_id: str, prompt_version: str) -> dict:
    """Overwrite the fields this script owns; everything else stays as written."""
    data["split"] = a.split
    data["topic"] = a.topic
    data["voices"] = dict(a.voices)
    data["generator"] = model_id
    data["prompt_version"] = prompt_version
    data["reviewed"] = False
    data["reviewed_by"] = None
    return data


def validate(data: dict, a: Assignment) -> list[str]:
    """Errors only — loader errors and lint findings; empty means usable.

    Warnings are never returned, so they are never sent back to the model: not the
    loader's warnings, and not the lint's notes (session_lint.session_notes, e.g. an
    allowed second word difference). The one loader warning that is really a label
    error — a deviation with expected_flag false, which the loader would count as a
    control — is checked here as an error of its own."""
    problems: list[str] = []
    if data.get("session_id") != a.session_id:
        problems.append(f"session_id is {data.get('session_id')!r}, verwacht {a.session_id!r}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{a.session_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            load_session(path)
        except SessionFormatError as exc:
            problems.append(f"loader: {exc}")
    for pair in data.get("pairs") or []:
        if isinstance(pair, dict) and pair.get("label") in DEVIATIONS and pair.get("expected_flag") is False:
            problems.append(f"{pair.get('pair_id')}: afwijking {pair.get('label')} met expected_flag false")
    problems += lint_session(data)
    return problems


def feedback_message(problems: list[str]) -> str:
    return ("De sessie voldoet niet aan de regels. Dit kwam uit de controle:\n\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nLos alle punten op en geef de volledige sessie opnieuw, "
              "met de controletabel en de JSON in één ```json-codeblok.")


# --------------------------------------------------------------------------- #
# Calling the model
# --------------------------------------------------------------------------- #

@dataclass
class Reply:
    text: str
    content: Any               # passed back unchanged as the assistant turn
    model: str
    usage: dict[str, int]
    stop_reason: str | None = None   # normalised: "end_turn", "max_tokens", "refusal", ...
    provider: str = ANTHROPIC


Caller = Callable[[str, list[dict]], Reply]


def anthropic_caller(client: Any, model: str, max_tokens: int = MAX_TOKENS) -> Caller:
    """A Caller backed by the real API. The system prompt is cached, since it is
    the same for every session and every retry."""
    def call(system: str, messages: list[dict]) -> Reply:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
        u = msg.usage
        usage = {
            "input_tokens": u.input_tokens or 0,
            "output_tokens": u.output_tokens or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        }
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return Reply(text, msg.content, msg.model, usage, msg.stop_reason, ANTHROPIC)
    return call


# Gemini finish reasons that mean the model would not (or may not) answer.
_GEMINI_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION",
                   "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "LANGUAGE", "OTHER"}
GEMINI_USAGE_FIELDS = ("prompt_token_count", "cached_content_token_count", "candidates_token_count",
                       "thoughts_token_count", "total_token_count")


def _gemini_stop(finish_reason: Any) -> str:
    name = getattr(finish_reason, "name", None) or str(finish_reason or "")
    name = name.split(".")[-1]
    if name == "MAX_TOKENS":
        return "max_tokens"
    if name in _GEMINI_BLOCKED:
        return "refusal"
    return "end_turn" if name in ("STOP", "") else name.lower()


def gemini_caller(client: Any, model: str, max_tokens: int = MAX_TOKENS) -> Caller:
    """A Caller backed by google-genai: the prompt as system instruction, the same
    user messages, and the model's own Content passed back on a retry (so any thought
    signatures stay with it). Usage is kept under Gemini's usage_metadata names."""
    from google.genai import types

    def to_content(message: dict) -> Any:
        if message["role"] == "user":
            return types.Content(role="user", parts=[types.Part(text=str(message["content"]))])
        content = message["content"]
        if isinstance(content, types.Content):
            return content
        return types.Content(role="model", parts=[types.Part(text=str(content))])

    def call(system: str, messages: list[dict]) -> Reply:
        resp = client.models.generate_content(
            model=model,
            contents=[to_content(m) for m in messages],
            config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens),
        )
        meta = resp.usage_metadata
        usage = {f: int(getattr(meta, f, 0) or 0) for f in GEMINI_USAGE_FIELDS} if meta else {}
        candidate = resp.candidates[0] if resp.candidates else None
        if candidate is None or candidate.content is None:
            block = getattr(resp.prompt_feedback, "block_reason", None) if resp.prompt_feedback else None
            stop = "refusal" if block else _gemini_stop(getattr(candidate, "finish_reason", None))
            return Reply("", types.Content(role="model", parts=[types.Part(text="")]),
                         resp.model_version or model, usage, stop, GEMINI)
        parts = candidate.content.parts or []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        return Reply(text, candidate.content, resp.model_version or model, usage,
                     _gemini_stop(candidate.finish_reason), GEMINI)
    return call


def _price_key(table: dict, model: str) -> str | None:
    """Exact id, else the longest table key the id starts with (gemini-3.8-flash-001 → gemini-3.8-flash)."""
    if model in table:
        return model
    keys = [k for k in table if model.startswith(k)]
    return max(keys, key=len) if keys else None


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    if provider_for(model) == GEMINI:
        key = _price_key(GEMINI_PRICES, model)
        if key is None:
            return None
        p_in, p_out = GEMINI_PRICES[key]
        out_tokens = usage.get("candidates_token_count", 0) + usage.get("thoughts_token_count", 0)
        return (usage.get("prompt_token_count", 0) * p_in + out_tokens * p_out) / 1_000_000
    key = _price_key(PRICES, model)
    if key is None:
        return None
    p_in, p_out, p_write, p_read = PRICES[key]
    return (usage.get("input_tokens", 0) * p_in
            + usage.get("output_tokens", 0) * p_out
            + usage.get("cache_creation_input_tokens", 0) * p_write
            + usage.get("cache_read_input_tokens", 0) * p_read) / 1_000_000


@dataclass
class Attempt:
    text: str
    problems: list[str]
    stop_reason: str | None


@dataclass
class Outcome:
    assignment: Assignment
    ok: bool
    data: dict | None
    attempts: list[Attempt] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    prompt_version: str = ""
    provider: str = ""

    @property
    def problems(self) -> list[str]:
        return self.attempts[-1].problems if self.attempts else []


def generate_one(call: Caller, system: str, a: Assignment, prompt_version: str,
                 max_retries: int = MAX_RETRIES) -> Outcome:
    """Ask for one session, feed loader/lint findings back, retry up to ``max_retries``."""
    messages: list[dict] = [{"role": "user", "content": user_message(a)}]
    out = Outcome(a, ok=False, data=None, prompt_version=prompt_version)
    for _ in range(max_retries + 1):
        reply = call(system, messages)
        out.model = reply.model or out.model
        out.provider = reply.provider
        for k, v in reply.usage.items():
            out.usage[k] = out.usage.get(k, 0) + int(v or 0)

        problems: list[str] = []
        data = None
        if reply.stop_reason == "max_tokens":
            problems.append("antwoord afgekapt (max_tokens bereikt)")
        elif reply.stop_reason == "refusal":
            problems.append("model weigerde (stop_reason=refusal)")
        if not problems:
            try:
                data = apply_overrides(extract_json(reply.text), a, reply.model, prompt_version)
                problems = validate(data, a)
            except ExtractError as exc:
                problems = [str(exc)]
        out.attempts.append(Attempt(reply.text, problems, reply.stop_reason))
        if data is not None:
            out.data = data
        if not problems:
            out.ok = True
            return out
        if reply.stop_reason == "refusal":
            return out
        messages.append({"role": "assistant", "content": reply.content})
        messages.append({"role": "user", "content": feedback_message(problems)})
    return out


# --------------------------------------------------------------------------- #
# Writing results
# --------------------------------------------------------------------------- #

def _dump(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def raw_markdown(out: Outcome) -> str:
    a = out.assignment
    parts = [f"# {a.session_id} — ruwe antwoorden ({out.model or 'onbekend model'})\n",
             f"split: {a.split} · onderwerp: {a.topic} · prompt: {out.prompt_version} · "
             f"status: {'geaccepteerd' if out.ok else 'afgekeurd'}\n"]
    for i, att in enumerate(out.attempts, 1):
        parts.append(f"\n## Poging {i}\n\n{att.text}\n")
        if att.problems:
            parts.append(f"\n### Bevindingen na poging {i}\n\n"
                         + "\n".join(f"- {p}" for p in att.problems) + "\n")
    return "".join(parts)


def write_outcome(out: Outcome, out_dir: Path) -> Path:
    sid = out.assignment.session_id
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    (out_dir / "raw" / f"{sid}.md").write_text(raw_markdown(out), encoding="utf-8")
    if out.ok:
        target = out_dir / f"{sid}.json"
        target.write_text(_dump(out.data), encoding="utf-8")
        stale = out_dir / "rejected" / f"{sid}.errors.md"
        for old in (stale, stale.with_name(f"{sid}.json")):
            old.unlink(missing_ok=True)
        return target
    rej = out_dir / "rejected"
    rej.mkdir(parents=True, exist_ok=True)
    if out.data is not None:
        (rej / f"{sid}.json").write_text(_dump(out.data), encoding="utf-8")
    lines = [f"# {sid} afgekeurd na {len(out.attempts)} poging(en)\n"]
    for i, att in enumerate(out.attempts, 1):
        lines.append(f"\n## Poging {i}\n\n" + "\n".join(f"- {p}" for p in att.problems) + "\n")
    errors = rej / f"{sid}.errors.md"
    errors.write_text("".join(lines), encoding="utf-8")
    return errors


_USAGE_LABELS = {
    "input_tokens": "in", "output_tokens": "uit", "cache_creation_input_tokens": "cache schrijven",
    "cache_read_input_tokens": "cache lezen",
    "prompt_token_count": "prompt", "cached_content_token_count": "waarvan cache",
    "candidates_token_count": "antwoord", "thoughts_token_count": "denken",
    "total_token_count": "totaal",
}


def usage_summary(usage: dict[str, int]) -> str:
    return " · ".join(f"{label} {usage[k]}" for k, label in _USAGE_LABELS.items() if k in usage)


def log_record(out: Outcome, duration_s: float | None = None) -> dict:
    return {
        "time": _dt.datetime.now().isoformat(timespec="seconds"),
        "session_id": out.assignment.session_id,
        "split": out.assignment.split,
        "status": "ok" if out.ok else "rejected",
        "attempts": len(out.attempts),
        "provider": out.provider,
        "model": out.model,
        "prompt_version": out.prompt_version,
        **out.usage,
        "cost_usd_estimate": cost_usd(out.model, out.usage),
        "duration_s": None if duration_s is None else round(duration_s, 1),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _numbers(first: int, last: int) -> list[int]:
    if first > last:
        raise SystemExit(f"--from {first} ligt na --to {last}")
    for n in (first, last):
        split_for(n)
    return list(range(first, last + 1))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Genereer synthetische sessies met de Claude API.")
    ap.add_argument("--from", dest="first", type=int, required=True)
    ap.add_argument("--to", dest="last", type=int, required=True)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"standaard {DEFAULT_MODEL}")
    ap.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT,
                    help=f"promptbestand (standaard {DEFAULT_PROMPT.name}); "
                         "prompt_version = bestandsnaam zonder .md")
    ap.add_argument("--overwrite", action="store_true", help="bestaande sessies opnieuw maken")
    ap.add_argument("--dry-run", action="store_true", help="alleen tonen wat er gemaakt zou worden")
    args = ap.parse_args(argv)

    try:
        numbers = _numbers(args.first, args.last)
    except ValueError as exc:
        ap.error(str(exc))

    model = args.model

    todo: list[Assignment] = []
    for n in numbers:
        a = assignment(n)
        exists = (args.out_dir / f"{a.session_id}.json").exists()
        action = "overschrijven" if exists and args.overwrite else "overslaan (bestaat)" if exists else "maken"
        print(f"{a.session_id}  {a.split:4}  {a.topic:45}  officer={a.voices['officer']}  "
              f"applicant={a.voices['applicant']}  interpreter={a.voices['interpreter']}  → {action}")
        if action != "overslaan (bestaat)":
            todo.append(a)
    prompt_version = prompt_version_of(args.prompt)
    print(f"\nmodel: {model} · prompt: {args.prompt.name} (prompt_version {prompt_version}) · "
          f"uitvoer: {args.out_dir}")
    if not args.prompt.exists():
        print(f"prompt niet gevonden: {args.prompt}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"--dry-run: {len(todo)} sessie(s) zouden gemaakt worden; geen API-aanroepen.")
        return 0
    if not todo:
        return 0
    system = args.prompt.read_text(encoding="utf-8")

    from app.config import settings
    provider = provider_for(model)
    if provider == GEMINI:
        from google import genai
        from google.genai import errors as api_errors
        if not settings.gemini_api_key:
            print("GEMINI_API_KEY ontbreekt in .env", file=sys.stderr)
            return 2
        call = gemini_caller(genai.Client(api_key=settings.gemini_api_key), model)
    else:
        import anthropic as api_errors
        if not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY ontbreekt in .env", file=sys.stderr)
            return 2
        call = anthropic_caller(api_errors.Anthropic(api_key=settings.anthropic_api_key), model)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    total_cost = 0.0
    for a in todo:
        print(f"\n[{a.session_id}] genereren …", flush=True)
        started = time.monotonic()
        try:
            out = generate_one(call, system, a, prompt_version)
        except api_errors.APIError as exc:
            failed += 1
            # status and the API's message only; never the request (which carries the key)
            status = getattr(exc, "status_code", None) or getattr(exc, "code", "")
            print(f"[{a.session_id}] API-fout: {type(exc).__name__} {status}: "
                  f"{str(getattr(exc, 'message', '') or '')[:300]}")
            continue
        path = write_outcome(out, args.out_dir)
        rec = log_record(out, time.monotonic() - started)
        with (args.out_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        cost = rec["cost_usd_estimate"]
        total_cost += cost or 0.0
        print(f"[{a.session_id}] {rec['status']} na {rec['attempts']} poging(en) · {out.provider} "
              f"{out.model} · {usage_summary(out.usage)} · "
              f"kosten ≈ {'?' if cost is None else f'${cost:.4f}'} · duur {rec['duration_s']} s → "
              f"{path.relative_to(args.out_dir)}")
        if not out.ok:
            failed += 1
            if a.split == "test":
                print(f"[{a.session_id}] {len(out.problems)} bevinding(en); test-sessie, details alleen in rejected/")
            else:
                for p in out.problems:
                    print(f"  - {p}")
    print(f"\n{len(todo) - failed} gelukt, {failed} mislukt · geschatte kosten ${total_cost:.4f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
