"""T9 — Security (EIS-6): evidence for a code review against BIO2 measures
8.24 (cryptography), 5.17 (authentication/MFA), 5.18 (privileged accounts /
access rights) and 8.15 (logging).

Static only: searches the inspected checkout for the controls each measure
asks about and records every hit (or the absence of hits) with file:line. The
verdict per measure is written by a human; this script makes no claims about
infrastructure that is not in the repo.

v2 (2026-10-01), changed so before/after fixes can be compared with ONE
instrument — rerun on both commits rather than comparing against v1 output:
- --repo: inspect any checkout (e.g. a worktree of an older commit);
- development (docker-compose.yml) and production (docker-compose.prod.yml,
  deploy/) configuration are reported separately;
- security-event logging also counts the audit() helper, not only log calls;
- transcript text in logs is found by parsing every log call (AST) at any
  level, instead of a one-line regex that missed multi-line calls;
- the story-of-ali-3 log exposure is only computed when some INFO-or-higher
  log call actually writes text; otherwise it is 0;
- comment lines (# or //) are skipped: the first after-run counted "Let's
  Encrypt" and a comment listing requirements as encryption controls.

Usage (from the eval checkout's root):
  uv run --project backend python eval/t9_security.py [--repo PATH] [--out DIR]
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = EVAL_ROOT / "eval" / "data" / "story-of-ali-3.script.txt"
LOG_TRUNCATION = 60  # chars the v1 code kept per logged fragment at INFO

APP = ["backend/app"]
DEV_CONFIG = ["docker-compose.yml", "backend/Dockerfile.dev", "frontend/Dockerfile.dev",
              "backend/.env.example"]
PROD_CONFIG = ["docker-compose.prod.yml", "deploy", "backend/Dockerfile", "frontend/Dockerfile",
               ".env.prod.example"]
ALL_CONFIG = DEV_CONFIG + PROD_CONFIG + ["backend/pyproject.toml"]
AUTH_FILES = ["backend/app/routers/auth.py", "backend/app/security.py",
              "backend/app/routers/sessions.py", "backend/app/routers/evaluations.py",
              "backend/app/cli.py"]

TLS = r"sslmode|ssl=|ssl_context|certfile|keyfile|rediss://|^\s*tls\s|Strict-Transport-Security|\"443:443\""
DEFAULT_CREDS = r"postgres:postgres|POSTGRES_PASSWORD=postgres\b"

CHECKS = {
    # 8.24 cryptography
    "password_hashing": (r"CryptContext|bcrypt|argon2", APP),
    "jwt_algorithm_and_secret": (r"algorithm|secret_key|jwt\.(en|de)code", APP),
    "tls_dev_config": (TLS, DEV_CONFIG),
    "tls_prod_config": (TLS, PROD_CONFIG),
    "encryption_at_rest": (r"encrypt|fernet|cipher|AES|pgcrypto", APP + ALL_CONFIG),
    "audio_written_plain": (r"write_bytes|UPLOAD_DIR", APP),
    "cookie_flags": (r"httponly|secure=|samesite", APP),
    # 5.17 authentication
    "mfa": (r"totp|otp|mfa|2fa|webauthn|second.factor|pyotp", APP + ["frontend/app", "frontend/lib"]),
    "rate_limit_or_lockout": (r"slowapi|limiter|rate.?limit|lockout|locked_until|login_max_failures|throttl",
                              APP + ALL_CONFIG),
    "password_policy": (r"min_length|len\(password\)|password.*<\s*\d|zxcvbn", APP),
    "token_revocation": (r"revok|blacklist|denylist|jti|token_version", APP),
    "token_lifetime": (r"access_token_expire_minutes", APP),
    # 5.18 accounts and access rights
    # Access roles only — "role" alone matches the speaker-role confirmation step.
    "roles_or_admin_flag": (r"is_admin|is_superuser|permission|user_role|access_role|Role\(|scopes?\s*=",
                            ["backend/app/models", "backend/app/security.py", "backend/app/routers"]),
    "account_management_cli": (r"create-user|deactivate-user|activate-user|list-users", ["backend/app/cli.py"]),
    "ownership_checks": (r"owner_id\s*==\s*current_user\.id", APP),
    "default_credentials_dev": (DEFAULT_CREDS, DEV_CONFIG),
    "default_credentials_prod": (DEFAULT_CREDS, PROD_CONFIG),
    "required_secrets_prod": (r"\$\{\w+:\?", PROD_CONFIG),
    "redis_password": (r"requirepass|redis://:", ALL_CONFIG),
    "least_privilege_db_role": (r"tolkcheck_app", PROD_CONFIG),
    "exposed_ports_dev": (r"^\s*-\s*\"\d+:\d+\"", ["docker-compose.yml"]),
    "exposed_ports_prod": (r"^\s*-\s*\"\d+:\d+\"", ["docker-compose.prod.yml"]),
    "admin_tools_dev": (r"adminer|pgadmin", ["docker-compose.yml"]),
    "admin_tools_prod": (r"^\s*(adminer|pgadmin)|image:\s*(adminer|dpage/pgadmin)", ["docker-compose.prod.yml"]),
    "container_user_prod": (r"^USER\b", ["backend/Dockerfile", "frontend/Dockerfile"]),
    # 8.15 logging
    "log_sink_and_level": (r"basicConfig|stream=|FileHandler|log_level", APP),
    "security_event_logging": (r"\blog\.|\blogger\.|\blogging\.|\baudit\(", AUTH_FILES),
    "raw_errors_returned_by_api": (r"^\s*error_message\s*:", ["backend/app/schemas/session.py"]),
}

LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
TEXT_NAMES = {"orig", "trans", "text", "texts", "source_text", "interp_text",
              "response_text", "cleaned", "known_terms", "user_content"}


def files_under(repo: Path, paths: list[str]) -> list[Path]:
    out = []
    for rel in paths:
        p = repo / rel
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += [f for f in sorted(p.rglob("*"))
                    if f.is_file() and "node_modules" not in f.parts
                    and (f.suffix in (".py", ".ts", ".tsx", ".sh", ".yml", ".yaml")
                         or f.name == "Caddyfile")]
    return out


def grep(repo: Path, pattern: str, paths: list[str]) -> list[str]:
    rx = re.compile(pattern, re.I | re.M)
    hits = []
    for f in files_under(repo, paths):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            # A control mentioned in a comment is not a control.
            if line.lstrip().startswith(("#", "//")):
                continue
            if rx.search(line):
                hits.append(f"{f.relative_to(repo).as_posix()}:{i}: {line.strip()[:150]}")
    return hits


def _is_text_access(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value == "text"
    if isinstance(node, ast.Attribute) and node.attr in ("text", "known_terms"):
        return True
    if isinstance(node, ast.Name):
        return node.id in TEXT_NAMES or node.id.endswith("_texts")
    return False


def _exposes_text(arg: ast.AST) -> bool:
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "len":
        return False
    return any(_is_text_access(n) for n in ast.walk(arg))


def text_log_calls(repo: Path) -> list[dict]:
    """Every log call in backend/app that passes transcript/translation text."""
    found = []
    for f in sorted((repo / "backend" / "app").rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id in ("log", "logger")
                    and n.func.attr in LOG_METHODS and any(_exposes_text(a) for a in n.args[1:])):
                found.append({"where": f"{f.relative_to(repo).as_posix()}:{n.lineno}",
                              "level": n.func.attr})
    return found


def log_exposure(text_calls: list[dict]) -> dict:
    visible = [c for c in text_calls if c["level"] not in ("debug",)]
    lines = [ln.strip() for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    utts = [re.sub(r"^(IND MEDEWERKER|Tolk|Ali):\s*", "", ln) for ln in lines]
    full = [u for u in utts if len(u) <= LOG_TRUNCATION] if visible else []
    return {
        "script": SCRIPT.relative_to(EVAL_ROOT).as_posix(),
        "text_log_calls_at_info_or_higher": len(visible),
        "truncation_chars": LOG_TRUNCATION,
        "utterances": len(utts),
        "logged_in_full": len(full),
        "examples_logged_in_full": full[:5],
        "note": ("No log call at INFO or higher writes text, so nothing of the script reaches "
                 "the default logs." if not visible else
                 "Every utterance appears in the log, at least its first 60 characters; "
                 "logged_in_full counts those that appear completely."),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=EVAL_ROOT, help="checkout to inspect")
    ap.add_argument("--out", type=Path, default=EVAL_ROOT / "eval" / "results" / "t9")
    args = ap.parse_args()
    repo = args.repo.resolve()
    args.out.mkdir(parents=True, exist_ok=True)

    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True).stdout.strip()

    text_calls = text_log_calls(repo)
    evidence = {
        "test": "T9 security (EIS-6), code review only",
        "instrument": "eval/t9_security.py v2",
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "inspected_repo": str(repo),
        "inspected_commit": git("rev-parse", "HEAD"),
        "inspected_branch": git("branch", "--show-current") or "(detached)",
        "checks": {name: {"pattern": pat, "searched": paths, "hits": grep(repo, pat, paths)}
                   for name, (pat, paths) in CHECKS.items()},
        "transcript_text_in_logs": text_calls,
        "log_exposure_story_of_ali_3": log_exposure(text_calls),
    }
    (args.out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    print(f"inspected {evidence['inspected_commit'][:7]} ({evidence['inspected_branch']})")
    for name, c in evidence["checks"].items():
        print(f"{name:32s} {len(c['hits']):3d} hit(s)")
    by_level: dict[str, int] = {}
    for c in text_calls:
        by_level[c["level"]] = by_level.get(c["level"], 0) + 1
    print(f"{'transcript_text_in_logs':32s} {len(text_calls):3d} call(s) {by_level}")
    e = evidence["log_exposure_story_of_ali_3"]
    print(f"log exposure: {e['logged_in_full']} of {e['utterances']} utterances logged in full")


if __name__ == "__main__":
    main()
