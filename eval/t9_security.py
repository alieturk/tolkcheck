"""T9 — Security (EIS-6): evidence for a code review against BIO2 measures
8.24 (cryptography), 5.17 (authentication/MFA), 5.18 (privileged accounts /
access rights) and 8.15 (logging).

Static only: greps the repo for the controls each measure asks about and
records every hit (or the absence of hits) with file:line, plus one measured
number — how many utterances of the synthetic test script would end up in the
logs in full, given that the pipeline logs transcript text at INFO truncated to
60 characters. The verdict per measure is written by a human in T9.md; it makes
no claims about infrastructure (TLS termination, disk encryption, network
segmentation) that is not in the repo.

Usage (from repo root):  uv run --project backend python eval/t9_security.py
Writes eval/results/t9/evidence.json.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "eval" / "results" / "t9"
SCRIPT = REPO / "eval" / "data" / "story-of-ali-3.script.txt"
LOG_TRUNCATION = 60  # chars; see the log.info calls in backend/app/pipeline.py and alignment.py

APP = ["backend/app"]
CONFIG = ["docker-compose.yml", "backend/Dockerfile", "backend/Dockerfile.dev",
          "backend/.env.example", "backend/pyproject.toml"]

CHECKS = {
    # 8.24 cryptography
    "password_hashing": (r"CryptContext|bcrypt|argon2", APP),
    "jwt_algorithm_and_secret": (r"algorithm|secret_key|jwt\.(en|de)code", APP),
    # Configuration only — "https" in comments/URLs is not a TLS setting.
    "tls_in_app_or_config": (r"sslmode|ssl=|ssl_context|--ssl-|certfile|keyfile|rediss://|tls_", APP + CONFIG),
    "encryption_at_rest": (r"encrypt|fernet|cipher|AES|pgcrypto", APP + CONFIG),
    "audio_written_plain": (r"write_bytes|UPLOAD_DIR", APP),
    "default_credentials_in_config": (r"postgres:postgres|POSTGRES_PASSWORD|requirepass", CONFIG),
    "cookie_flags": (r"httponly|secure=|samesite", APP),
    # 5.17 authentication
    "mfa": (r"totp|otp|mfa|2fa|webauthn|second.factor|pyotp", APP + ["frontend/app", "frontend/lib"]),
    "rate_limit_or_lockout": (r"slowapi|limiter|rate.?limit|lockout|failed_attempts|throttl", APP + CONFIG),
    "password_policy": (r"min_length|len\(password\)|password.*<\s*\d|zxcvbn", APP),
    "token_revocation": (r"revok|blacklist|denylist|jti|token_version", APP),
    "token_lifetime": (r"access_token_expire_minutes", APP),
    # 5.18 accounts and access rights
    # Access roles only — "role" alone matches the speaker-role confirmation step.
    "roles_or_admin_flag": (r"is_admin|is_superuser|permission|user_role|access_role|Role\(|scopes?\s*=",
                            ["backend/app/models", "backend/app/security.py", "backend/app/routers"]),
    "account_provisioning": (r"create-user|_create_user|is_active", APP),
    "ownership_checks": (r"owner_id\s*==\s*current_user\.id", APP),
    "exposed_service_ports": (r"^\s*-\s*\"\d+:\d+\"", ["docker-compose.yml"]),
    "admin_tools": (r"adminer|pgadmin", ["docker-compose.yml"]),
    "container_user": (r"^USER\b", ["backend/Dockerfile", "backend/Dockerfile.dev"]),
    # 8.15 logging
    "log_sink_and_level": (r"basicConfig|stream=|FileHandler|log_level", APP),
    "auth_event_logging": (r"log\.|logger\.|logging\.", ["backend/app/routers/auth.py",
                                                         "backend/app/security.py",
                                                         "backend/app/routers/sessions.py",
                                                         "backend/app/routers/evaluations.py",
                                                         "backend/app/cli.py"]),
    "transcript_text_in_logs": (r"log\.(info|warning|error)\(.*%r", ["backend/app/pipeline.py",
                                                                     "backend/app/services/alignment.py"]),
    "raw_errors_returned_by_api": (r"error_message", ["backend/app/schemas/session.py",
                                                    "backend/app/pipeline.py"]),
}


def files_under(paths: list[str]) -> list[Path]:
    out = []
    for rel in paths:
        p = REPO / rel
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += [f for f in sorted(p.rglob("*"))
                    if f.suffix in (".py", ".ts", ".tsx") and "node_modules" not in f.parts]
    return out


def grep(pattern: str, paths: list[str]) -> list[str]:
    rx = re.compile(pattern, re.I | re.M)
    hits = []
    for f in files_under(paths):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{f.relative_to(REPO).as_posix()}:{i}: {line.strip()[:150]}")
    return hits


def log_exposure() -> dict:
    """Utterances of the synthetic script that fit in one 60-char log fragment."""
    lines = [ln.strip() for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    # drop the speaker label on the first turns ("Tolk: ...") — not spoken text
    utts = [re.sub(r"^(IND MEDEWERKER|Tolk|Ali):\s*", "", ln) for ln in lines]
    full = [u for u in utts if len(u) <= LOG_TRUNCATION]
    return {
        "script": SCRIPT.relative_to(REPO).as_posix(),
        "truncation_chars": LOG_TRUNCATION,
        "utterances": len(utts),
        "logged_in_full": len(full),
        "logged_truncated": len(utts) - len(full),
        "examples_logged_in_full": full[:5],
        "note": "Every utterance appears in the log, at least its first 60 characters; "
                "these counts say how many appear completely.",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = {
        "test": "T9 security (EIS-6), code review only",
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                                     capture_output=True, text=True).stdout.strip(),
        "checks": {name: {"pattern": pat, "searched": paths, "hits": grep(pat, paths)}
                   for name, (pat, paths) in CHECKS.items()},
        "log_exposure_story_of_ali_3": log_exposure(),
    }
    (OUT / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    for name, c in evidence["checks"].items():
        print(f"{name:32s} {len(c['hits']):3d} hit(s)")
    e = evidence["log_exposure_story_of_ali_3"]
    print(f"log exposure: {e['logged_in_full']} of {e['utterances']} utterances fit in "
          f"{e['truncation_chars']} chars (logged in full)")


if __name__ == "__main__":
    main()
