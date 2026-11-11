"""Generate synthetic DV4 test sessions with the Claude API (prompt tolkcheck-sessies-v2).

This script only makes data. It chooses no threshold, scores nothing, and the
measurement code (sessions.py, session_lint.py, detection_check.py) is untouched:
every generated session must pass ``sessions.load_session`` and
``session_lint.lint_session`` before it is written.

What is fixed per session number n, not left to the model:

* split   — dev for 20–29 and 50–59; test for 30–49, 60–69 and 70–89
* topic   — (n − 20) mod 7, see TOPICS
* voices  — officer and applicant rotate a/b/c with n mod 3 (the rotation S20–S24
            already use); the interpreter is always vb_interp_a

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

EVAL_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = EVAL_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
for _p in (EVAL_DIR, BACKEND_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from session_lint import PROMPT_VERSION, lint_session  # noqa: E402
from sessions import SessionFormatError, load_session  # noqa: E402

PROMPT_PATH = EVAL_DIR / "prompts" / f"{PROMPT_VERSION}.md"
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
}


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


def assignment(n: int) -> Assignment:
    split = split_for(n)  # raises for numbers outside the range
    return Assignment(n, f"S{n}", split, topic_for(n), voices_for(n))


def user_message(a: Assignment) -> str:
    spec = {"session_id": a.session_id, "split": a.split, "topic": a.topic, "voices": a.voices}
    return ("Maak deze sessie volgens de instructies.\n\n```json\n"
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


def apply_overrides(data: dict, a: Assignment, model_id: str) -> dict:
    """Overwrite the fields this script owns; everything else stays as written."""
    data["split"] = a.split
    data["topic"] = a.topic
    data["voices"] = dict(a.voices)
    data["generator"] = model_id
    data["prompt_version"] = PROMPT_VERSION
    data["reviewed"] = False
    data["reviewed_by"] = None
    return data


def validate(data: dict, a: Assignment) -> list[str]:
    """Loader errors and warnings plus every lint finding; empty means usable."""
    problems: list[str] = []
    if data.get("session_id") != a.session_id:
        problems.append(f"session_id is {data.get('session_id')!r}, verwacht {a.session_id!r}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{a.session_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            session = load_session(path)
            problems += [f"loader: {w}" for w in session.warnings]
        except SessionFormatError as exc:
            problems.append(f"loader: {exc}")
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
    stop_reason: str | None = None


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
        return Reply(text, msg.content, msg.model, usage, msg.stop_reason)
    return call


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    p_in, p_out, p_write, p_read = price
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

    @property
    def problems(self) -> list[str]:
        return self.attempts[-1].problems if self.attempts else []


def generate_one(call: Caller, system: str, a: Assignment, max_retries: int = MAX_RETRIES) -> Outcome:
    """Ask for one session, feed loader/lint findings back, retry up to ``max_retries``."""
    messages: list[dict] = [{"role": "user", "content": user_message(a)}]
    out = Outcome(a, ok=False, data=None)
    for _ in range(max_retries + 1):
        reply = call(system, messages)
        out.model = reply.model or out.model
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
                data = apply_overrides(extract_json(reply.text), a, reply.model)
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
             f"split: {a.split} · onderwerp: {a.topic} · prompt: {PROMPT_VERSION} · "
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


def log_record(out: Outcome) -> dict:
    return {
        "time": _dt.datetime.now().isoformat(timespec="seconds"),
        "session_id": out.assignment.session_id,
        "split": out.assignment.split,
        "status": "ok" if out.ok else "rejected",
        "attempts": len(out.attempts),
        "model": out.model,
        "prompt_version": PROMPT_VERSION,
        **out.usage,
        "cost_usd_estimate": cost_usd(out.model, out.usage),
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
    ap.add_argument("--model", default=None, help="standaard settings.llm_model")
    ap.add_argument("--overwrite", action="store_true", help="bestaande sessies opnieuw maken")
    ap.add_argument("--dry-run", action="store_true", help="alleen tonen wat er gemaakt zou worden")
    args = ap.parse_args(argv)

    try:
        numbers = _numbers(args.first, args.last)
    except ValueError as exc:
        ap.error(str(exc))

    model = args.model
    if model is None:
        from app.config import settings
        model = settings.llm_model

    todo: list[Assignment] = []
    for n in numbers:
        a = assignment(n)
        exists = (args.out_dir / f"{a.session_id}.json").exists()
        action = "overschrijven" if exists and args.overwrite else "overslaan (bestaat)" if exists else "maken"
        print(f"{a.session_id}  {a.split:4}  {a.topic:45}  officer={a.voices['officer']}  "
              f"applicant={a.voices['applicant']}  interpreter={a.voices['interpreter']}  → {action}")
        if action != "overslaan (bestaat)":
            todo.append(a)
    print(f"\nmodel: {model} · prompt: {PROMPT_PATH.name} · uitvoer: {args.out_dir}")
    if args.dry_run:
        print(f"--dry-run: {len(todo)} sessie(s) zouden gemaakt worden; geen API-aanroepen.")
        return 0
    if not todo:
        return 0
    if not PROMPT_PATH.exists():
        print(f"prompt niet gevonden: {PROMPT_PATH}", file=sys.stderr)
        return 2
    system = PROMPT_PATH.read_text(encoding="utf-8")

    import anthropic

    from app.config import settings
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY ontbreekt in .env", file=sys.stderr)
        return 2
    call = anthropic_caller(anthropic.Anthropic(api_key=settings.anthropic_api_key), model)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    total_cost = 0.0
    for a in todo:
        print(f"\n[{a.session_id}] genereren …", flush=True)
        try:
            out = generate_one(call, system, a)
        except anthropic.APIError as exc:
            failed += 1
            print(f"[{a.session_id}] API-fout: {type(exc).__name__}: {getattr(exc, 'message', exc)}")
            continue
        path = write_outcome(out, args.out_dir)
        rec = log_record(out)
        with (args.out_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        cost = rec["cost_usd_estimate"]
        total_cost += cost or 0.0
        print(f"[{a.session_id}] {rec['status']} na {rec['attempts']} poging(en) · model {out.model} · "
              f"in {rec.get('input_tokens', 0)} · uit {rec.get('output_tokens', 0)} · "
              f"cache schrijven {rec.get('cache_creation_input_tokens', 0)} · "
              f"cache lezen {rec.get('cache_read_input_tokens', 0)} · "
              f"kosten ≈ {'?' if cost is None else f'${cost:.4f}'} → {path.relative_to(args.out_dir)}")
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
