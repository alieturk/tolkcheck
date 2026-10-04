"""T8 — Privacy (EIS-5): where does hearing audio and transcript data end up?

Runs the REAL backend (uvicorn) and the REAL ARQ worker as subprocesses against
an isolated test environment, pushes one synthetic session through the normal
API flow (login -> upload -> start -> confirm roles), then collects evidence:

  disk   : files in the run's uploads/ dir; any copy of the input audio (by
           sha256) under the work dir, %TEMP% and backend/
  db     : sessions/evaluations rows for the run, column types that could hold
           audio, large objects, which text columns hold transcript content
  redis  : every key ARQ left behind, its TTL, and whether any value contains
           audio bytes (RIFF header) or transcript/canary text
  logs   : api.log + worker.log scanned for hand-picked canaries from the
           script (names, places) and for every transcript segment the
           pipeline itself stored
  retention: whether any retention/cleanup mechanism exists to trigger

Nothing here changes pipeline logic. Test-environment-only settings:
  - DATABASE_URL -> separate database tolkcheck_t8
  - REDIS_URL    -> fakeredis TCP server in this process (no Windows Redis build
                    on conda-forge; protocol-compatible, in-memory, no RDB/AOF)
  - ANTHROPIC_BASE_URL -> unroutable local address, so the LLM step fails
                    locally and NO transcript leaves the machine (Claude step is
                    out of scope for the metrics; see RESULTS deviations)
  - COOKIE_SECURE=false, because the harness talks plain http to 127.0.0.1
  - cwd = a work dir outside the repo, so uploads/ is isolated from dev data

Usage (from repo root):
  uv run --project backend --with "fakeredis[lua]==2.38.0" --with psutil \
      python eval/t8_privacy.py --audio C:/Users/cultro/Downloads/story-of-ali-3.wav

HF_TOKEN is read from the environment, else from backend/.env. It is passed to
the worker and never written to any output.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
DEFAULT_WORKDIR = Path.home() / "tolkcheck-t8-env"
DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/tolkcheck_t8"
REDIS_PORT = 6390
API_PORT = 8765

# Hand-picked from eval/data/story-of-ali-3.script.txt: names of (synthetic)
# people, places and story details. Any of these in a log = transcript or
# personal data leaking into logs.
CANARIES = [
    "Demir", "Sanne", "Vermeer", "Derya", "Diyarbak", "gazeteci", "journalist",
    "Istanboel", "stanbul", "kardeş", "dreigtelefoon", "corruptie", "yolsuzluk",
    "negenentwintig", "Yirmi dokuz", "briefje", "politie", "polis",
]


# Same steps as `arq app.worker.WorkerSettings` (arq/cli.py), except that
# arq.worker.log_redis_info is replaced by a no-op: it only logs one startup
# line from `INFO Server/Memory/Clients`, and fakeredis does not implement
# INFO, so the unpatched worker exits before taking any job. Every command
# arq uses to queue and run jobs is supported by fakeredis.
WORKER_LAUNCHER = """
import logging.config
import arq.worker as w
from arq.logs import default_log_config

async def _no_redis_info(*args, **kwargs):
    pass

w.log_redis_info = _no_redis_info
from app.worker import WorkerSettings
logging.config.dictConfig(default_log_config(False))
w.run_worker(WorkerSettings, burst=False)
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_hf_token() -> str:
    tok = os.environ.get("HF_TOKEN", "")
    env_file = BACKEND / ".env"
    if not tok and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().upper().startswith("HF_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
    return tok


def environment_info() -> dict:
    def pkg(name: str) -> str | None:
        try:
            from importlib.metadata import version
            return version(name)
        except Exception:
            return None

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True).stdout.strip()

    import psutil  # eval-only dependency, passed via `uv run --with psutil`
    return {
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "git_dirty_files": git("status", "--porcelain").splitlines(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "cpu_count": os.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "packages": {p: pkg(p) for p in (
            "torch", "torchaudio", "faster-whisper", "pyannote.audio",
            "sentence-transformers", "arq", "redis", "fakeredis", "sqlalchemy",
            "fastapi", "uvicorn")},
    }


# ── fakeredis server ─────────────────────────────────────────────────────────

def start_fake_redis() -> object:
    from fakeredis import TcpFakeServer
    server = TcpFakeServer(("127.0.0.1", REDIS_PORT), server_type="redis")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def wait_port(port: int, timeout: float) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError(f"port {port} not open after {timeout}s")


def wait_for_line(log: Path, needle: str, proc: subprocess.Popen, timeout: float) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited ({proc.returncode}) before '{needle}'; see {log}")
        if log.exists() and needle in log.read_text(encoding="utf-8", errors="replace"):
            return
        time.sleep(2)
    raise TimeoutError(f"'{needle}' not seen in {log} after {timeout}s")


# ── evidence collection ──────────────────────────────────────────────────────

def find_audio_copies(digest: str, size: int, roots: list[Path], since: float) -> list[dict]:
    """Every file under roots with the input's exact size+sha256, or any audio-like
    file modified since the run started."""
    hits = []
    audio_ext = {".wav", ".mp3", ".flac", ".ogg", ".webm", ".m4a", ".mp4"}
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".venv", "node_modules", ".git")]
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    st = p.stat()
                except OSError:
                    continue
                same = st.st_size == size and sha256(p) == digest
                recent_audio = p.suffix.lower() in audio_ext and st.st_mtime >= since
                if same or recent_audio:
                    hits.append({"path": str(p), "bytes": st.st_size,
                                 "identical_to_input": same,
                                 "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat()})
    return hits


def scan_text(text: str, needles: list[str]) -> dict[str, int]:
    low = text.lower()
    return {n: low.count(n.lower()) for n in needles if low.count(n.lower())}


async def db_evidence(session_id: str) -> dict:
    import asyncpg
    conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5433/tolkcheck_t8")
    try:
        out: dict = {}
        q_session = ("SELECT id::text, status::text, filename, audio_path, error_code, "
                     "left(error_message, 300) AS error_message, duration_seconds "
                     "FROM sessions WHERE id = $1::uuid")
        out["query_session"] = q_session
        row = await conn.fetchrow(q_session, session_id)
        out["session_row"] = dict(row) if row else None

        q_cols = ("SELECT table_name, column_name, data_type FROM information_schema.columns "
                  "WHERE table_schema='public' ORDER BY table_name, ordinal_position")
        out["query_columns"] = q_cols
        cols = [dict(r) for r in await conn.fetch(q_cols)]
        out["binary_columns"] = [c for c in cols if c["data_type"] in ("bytea", "oid")]
        out["large_objects"] = await conn.fetchval("SELECT count(*) FROM pg_largeobject_metadata")

        ev = await conn.fetchrow("SELECT * FROM evaluations WHERE session_id = $1::uuid", session_id)
        out["evaluation_row_exists"] = ev is not None
        stored_texts: list[str] = []
        if ev:
            ev = dict(ev)
            summary = {}
            for k, v in ev.items():
                if v is None:
                    summary[k] = None
                elif isinstance(v, (str, bytes)) and len(v) > 120:
                    summary[k] = f"<{type(v).__name__} len={len(v)}>"
                else:
                    summary[k] = v if isinstance(v, (int, float, bool)) else str(v)[:120]
            out["evaluation_columns_filled"] = summary
            transcript = ev.get("transcript")
            if isinstance(transcript, str):
                transcript = json.loads(transcript)
            if transcript:
                out["transcript_segments_stored"] = len(transcript)
                stored_texts = [s.get("text", "") for s in transcript if s.get("text")]
        out["counts"] = {
            "sessions_total": await conn.fetchval("SELECT count(*) FROM sessions"),
            "evaluations_total": await conn.fetchval("SELECT count(*) FROM evaluations"),
        }
        return out, stored_texts
    finally:
        await conn.close()


def redis_evidence(needles: list[str]) -> dict:
    import redis
    r = redis.Redis(host="127.0.0.1", port=REDIS_PORT)
    keys = []
    for k in sorted(r.keys("*")):
        t = r.type(k).decode()
        if t == "string":
            raw = r.get(k) or b""
        elif t == "zset":
            raw = b"".join(m for m, _ in r.zrange(k, 0, -1, withscores=True))
        elif t == "list":
            raw = b"".join(r.lrange(k, 0, -1))
        elif t == "hash":
            raw = b"".join(a + b for a, b in r.hgetall(k).items())
        elif t == "set":
            raw = b"".join(r.smembers(k))
        else:
            raw = b""
        txt = raw.decode("utf-8", errors="replace")
        keys.append({
            "key": k.decode(errors="replace"), "type": t, "ttl_s": r.ttl(k),
            "value_bytes": len(raw), "contains_riff_header": b"RIFF" in raw,
            "canary_hits": scan_text(txt, needles),
        })
    return {"dbsize": r.dbsize(), "keys": keys}


def retention_evidence() -> dict:
    """Is there anything to trigger? Static check of the code, not a run."""
    sys.path.insert(0, str(BACKEND))
    hits = []
    pat = re.compile(r"retention|cron|unlink\(|os\.remove|shutil\.rmtree|timedelta\(days|delete\(", re.I)
    for p in sorted((BACKEND / "app").rglob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{p.relative_to(REPO).as_posix()}:{i}: {line.strip()}")
    worker_src = (BACKEND / "app" / "worker.py").read_text(encoding="utf-8")
    return {
        "grep_pattern": pat.pattern,
        "grep_hits_in_backend_app": hits,
        "worker_settings_defines_cron_jobs": "cron_jobs" in worker_src,
        "sessions_router_has_delete_route": "@router.delete" in
            (BACKEND / "app" / "routers" / "sessions.py").read_text(encoding="utf-8"),
    }


# ── main flow ────────────────────────────────────────────────────────────────

async def drive_api(audio: Path, email: str, password: str, out: dict, log) -> str:
    import httpx
    base = f"http://127.0.0.1:{API_PORT}"
    async with httpx.AsyncClient(base_url=base, timeout=120) as c:
        r = await c.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        with open(audio, "rb") as f:
            r = await c.post("/sessions", data={"language": "tr"},
                             files={"audio": (audio.name, f, "audio/wav")})
        r.raise_for_status()
        sid = r.json()["session_id"]
        log(f"uploaded session_id={sid}")
        out["timeline"].append({"t": time.time(), "event": "uploaded", "session_id": sid})
        (await c.post(f"/sessions/{sid}/start")).raise_for_status()
        out["timeline"].append({"t": time.time(), "event": "phase_a_enqueued"})

        status = await poll(c, sid, {"awaiting_role_confirmation", "failed"}, log)
        out["timeline"].append({"t": time.time(), "event": f"phase_a_end:{status}"})
        out["disk_after_phase_a"] = sorted(p.name for p in (Path.cwd() / "uploads").iterdir())
        if status == "failed":
            return sid

        # Pick roles from Whisper's per-segment language, the same signal
        # role_check.py uses. Role correctness is irrelevant to T8; recorded anyway.
        ev = (await c.get(f"/evaluations/{sid}")).json()
        per_spk: dict[str, dict[str, int]] = {}
        for seg in ev.get("transcript") or []:
            d = per_spk.setdefault(seg["speaker"], {})
            d[seg.get("language", "?")] = d.get(seg.get("language", "?"), 0) + 1
        share_tr = {s: d.get("tr", 0) / sum(d.values()) for s, d in per_spk.items()}
        ranked = sorted(share_tr, key=share_tr.get)
        officer, interpreter, client = ranked[0], ranked[len(ranked) // 2], ranked[-1]
        out["role_choice"] = {"lang_counts_per_speaker": per_spk, "officer": officer,
                              "interpreter": interpreter, "client": client,
                              "rule": "client=max Turkish share, officer=min, interpreter=middle"}
        log(f"roles: {out['role_choice']}")
        (await c.post(f"/sessions/{sid}/confirm-roles",
                      json={"interpreter_speaker": interpreter, "client_speaker": client})
         ).raise_for_status()
        out["timeline"].append({"t": time.time(), "event": "phase_b_enqueued"})
        status = await poll(c, sid, {"completed", "failed"}, log)
        out["timeline"].append({"t": time.time(), "event": f"phase_b_end:{status}"})
        return sid


async def poll(c, sid: str, done: set[str], log, timeout: float = 3 * 3600) -> str:
    end, last = time.time() + timeout, None
    while time.time() < end:
        st = (await c.get(f"/sessions/{sid}")).json()["status"]
        if st != last:
            log(f"status={st}")
            last = st
        if st in done:
            return st
        await asyncio.sleep(5)
    raise TimeoutError(f"session {sid} still {last} after {timeout}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    ap.add_argument("--out", type=Path, default=REPO / "eval" / "results" / "t8")
    args = ap.parse_args()

    t0 = time.time()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.out / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    work = args.workdir / stamp
    (work / "uploads").mkdir(parents=True, exist_ok=True)
    os.chdir(work)

    progress = open(out_dir / "progress.log", "a", encoding="utf-8")

    def log(msg: str) -> None:
        line = f"{dt.datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        progress.write(line + "\n")
        progress.flush()

    hf = read_hf_token()
    if not hf:
        log("HF_TOKEN not set (env or backend/.env): diarisation will fail. Aborting.")
        return 2

    audio = args.audio.resolve()
    evidence: dict = {
        "test": "T8 privacy (EIS-5)", "started": dt.datetime.now().isoformat(),
        "environment": environment_info(), "workdir": str(work),
        "input": {"path": str(audio), "bytes": audio.stat().st_size, "sha256": sha256(audio)},
        "test_env_overrides": ["DATABASE_URL=tolkcheck_t8", f"REDIS_URL=fakeredis:{REDIS_PORT}",
                               "worker started via WORKER_LAUNCHER (arq INFO log line disabled)",
                               "ANTHROPIC_BASE_URL=http://127.0.0.1:9 (unroutable)",
                               "COOKIE_SECURE=false", f"cwd={work}"],
        "timeline": [],
    }
    log(f"input sha256={evidence['input']['sha256']}  workdir={work}")

    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ANTHROPIC")}
    env.update({
        "DATABASE_URL": DB_URL, "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}",
        "SECRET_KEY": secrets.token_hex(32), "COOKIE_SECURE": "false",
        "HF_TOKEN": hf, "ANTHROPIC_API_KEY": "t8-no-real-key",
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:9", "LOG_LEVEL": "INFO",
        "PYTHONPATH": str(BACKEND), "PYTHONIOENCODING": "utf-8",
    })

    start_fake_redis()
    wait_port(REDIS_PORT, 10)

    # Account via the operator CLI's own function, against the T8 database.
    email, password = "t8-tester@example.test", secrets.token_urlsafe(16)
    subprocess.run([sys.executable, "-c",
                    "import asyncio,sys; from app.cli import _create_user; "
                    "asyncio.run(_create_user(sys.argv[1], sys.argv[2]))", email, password],
                   env=env, check=False, capture_output=True)

    api_log, worker_log = out_dir / "api.log", out_dir / "worker.log"
    procs = []
    try:
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(API_PORT)], env=env, cwd=work,
            stdout=open(api_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen(
            [sys.executable, "-c", WORKER_LAUNCHER], env=env, cwd=work,
            stdout=open(worker_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        wait_port(API_PORT, 120)
        log("api up; waiting for worker to load LaBSE + Whisper (first run downloads weights)")
        wait_for_line(worker_log, "Whisper ready.", procs[1], timeout=2 * 3600)
        log("worker ready")

        run_start = time.time()
        sid = asyncio.run(drive_api(audio, email, password, evidence, log))
        evidence["session_id"] = sid
        evidence["processing_seconds"] = round(time.time() - run_start, 1)
        time.sleep(3)  # let the worker flush its last log lines

        # ── evidence ──
        upl = work / "uploads"
        evidence["disk"] = {
            "uploads_dir": str(upl),
            "uploads_after_processing": [
                {"name": p.name, "bytes": p.stat().st_size,
                 "identical_to_input": sha256(p) == evidence["input"]["sha256"]}
                for p in sorted(upl.iterdir())],
            "copies_found": find_audio_copies(
                evidence["input"]["sha256"], evidence["input"]["bytes"],
                [work, Path(os.environ.get("TEMP", work)), BACKEND], run_start),
            "search_roots": [str(work), os.environ.get("TEMP", ""), str(BACKEND)],
        }
        db, stored_texts = asyncio.run(db_evidence(sid))
        evidence["db"] = db
        # Log needles: canaries + 25-char snippets of every stored transcript segment
        seg_needles = sorted({t.strip()[:25] for t in stored_texts if len(t.strip()) >= 25})
        evidence["redis"] = redis_evidence(CANARIES + seg_needles)
        logs = {}
        for name, p in (("api.log", api_log), ("worker.log", worker_log)):
            txt = p.read_text(encoding="utf-8", errors="replace")
            logs[name] = {
                "lines": txt.count("\n"),
                "canary_hits": scan_text(txt, CANARIES),
                "transcript_segment_hits": sum(1 for n in seg_needles if n.lower() in txt.lower()),
                "transcript_segments_checked": len(seg_needles),
                "session_id_mentions": txt.count(sid),
                "audio_filename_mentions": txt.count(sid + ".wav"),
            }
        evidence["logs"] = logs
        evidence["retention"] = retention_evidence()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(30)
            except subprocess.TimeoutExpired:
                p.kill()
        evidence["runtime_seconds_total"] = round(time.time() - t0, 1)
        (out_dir / "evidence.json").write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        log(f"evidence written to {out_dir / 'evidence.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
