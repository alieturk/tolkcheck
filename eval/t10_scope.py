"""T10 — Scope (EIS-2): no interpreter score, no link between sessions, no link
to interpreter identity.

Reads the schema from a database built by the repo's own Alembic migrations
(`alembic upgrade head`), not from the SQLAlchemy models, so it reflects what a
deployment actually gets. Then runs three mechanical checks and greps the code
paths that write and display the relevant columns. The verdict is written by a
human in RESULTS.md; this script only produces the evidence.

Usage (from repo root, Postgres with a migrated tolkcheck_t8 on :5433):
  uv run --project backend python eval/t10_scope.py [--repo PATH] [--out DIR]

--repo inspects another checkout (the database must be migrated to that
checkout's head; evidence.json records both so a mismatch is visible).
Writes <out>/schema.sql (pg_dump --schema-only) and <out>/evidence.json.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

import asyncpg

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "eval" / "results" / "t10"
DSN = "postgresql://postgres:postgres@localhost:5433/tolkcheck_t8"
PG_DUMP = Path.home() / "tolkcheck-postgres" / "env" / "Library" / "bin" / "pg_dump.exe"

SCORE_COL = re.compile(r"score", re.I)
IDENTITY_COL = re.compile(r"interpreter|tolk|speaker|name|email|case", re.I)
FREE_TEXT_TYPES = {"text", "character varying"}

# Code locations that write or show the columns found above.
CODE_GREPS = {
    "score_columns_written": (r"eval_row\.\w*score\w*\s*=", ["backend/app/pipeline.py"]),
    "score_shown_in_ui": (r"overall_score|statusLabel\s*=|Gemiddelde nauwkeurigheid|\"Goed\"|\"Voldoende\"",
                          ["frontend/app/sessions/[id]/EvaluationView.tsx"]),
    "llm_prompt_role": (r"beoordelaar|eindoordeel|Samenvattende beoordeling",
                        ["backend/app/services/feedback.py"]),
    "cross_session_queries": (r"select\(Session\)|select\(Evaluation\)",
                              ["backend/app/routers/sessions.py", "backend/app/routers/evaluations.py",
                               "backend/app/pipeline.py", "backend/app/services/retrieval.py"]),
    "product_framing": (r"kwaliteit", ["frontend/app/page.tsx", "frontend/app/upload/page.tsx"]),
}


def _alembic_head(repo: Path) -> str | None:
    """The revision no other migration in the checkout points back to."""
    revs, downs = set(), set()
    for f in (repo / "backend" / "alembic" / "versions").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        r = re.search(r"^revision[^=]*=\s*['\"](\w+)['\"]", src, re.M)
        d = re.search(r"^down_revision[^=]*=\s*['\"](\w+)['\"]", src, re.M)
        if r:
            revs.add(r.group(1))
        if d:
            downs.add(d.group(1))
    heads = revs - downs
    return heads.pop() if len(heads) == 1 else None


def grep(pattern: str, files: list[str], repo: Path = REPO) -> list[str]:
    rx = re.compile(pattern)
    hits = []
    for rel in files:
        p = repo / rel
        if not p.exists():
            hits.append(f"{rel}: <missing>")
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:160]}")
    return hits


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    repo, out = args.repo.resolve(), args.out
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PGPASSWORD": "postgres"}
    subprocess.run([str(PG_DUMP), "-h", "localhost", "-p", "5433", "-U", "postgres",
                    "--schema-only", "--no-owner", "-f", str(out / "schema.sql"), "tolkcheck_t8"],
                   env=env, check=True)

    conn = await asyncpg.connect(DSN)
    try:
        revision = await conn.fetchval("SELECT version_num FROM alembic_version")
        cols = [dict(r) for r in await conn.fetch(
            "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name <> 'alembic_version' "
            "ORDER BY table_name, ordinal_position")]
        fks = [dict(r) for r in await conn.fetch(
            "SELECT conrelid::regclass::text AS from_table, confrelid::regclass::text AS to_table, "
            "conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE contype='f' "
            "ORDER BY 1")]
    finally:
        await conn.close()

    tables = sorted({c["table_name"] for c in cols})
    evidence = {
        "test": "T10 scope (EIS-2)",
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                     capture_output=True, text=True).stdout.strip(),
        "repo_head_migration": _alembic_head(repo),
        "alembic_revision": revision,
        "tables": {t: [f"{c['column_name']} {c['data_type']}" for c in cols if c["table_name"] == t]
                   for t in tables},
        "foreign_keys": fks,
        "check_1_score_columns": [f"{c['table_name']}.{c['column_name']} ({c['data_type']})"
                                  for c in cols if SCORE_COL.search(c["column_name"])],
        "check_2_session_links": {
            "foreign_keys_touching_sessions": [f for f in fks if "sessions" in (f["from_table"], f["to_table"])],
            "tables_referencing_more_than_one_session": [
                f["from_table"] for f in fks
                if f["to_table"] == "sessions" and "UNIQUE" not in f["definition"]
                and f["from_table"] != "evaluations"],
            "shared_attributes_on_sessions": [
                f"sessions.{c['column_name']} ({c['data_type']})" for c in cols
                if c["table_name"] == "sessions" and c["column_name"] in ("owner_id", "ind_case_id")],
        },
        "check_3_identity_columns": [f"{c['table_name']}.{c['column_name']} ({c['data_type']})"
                                     for c in cols if IDENTITY_COL.search(c["column_name"])],
        "free_text_columns_user_can_fill": [
            f"sessions.{c['column_name']} ({c['data_type']})" for c in cols
            if c["table_name"] == "sessions" and c["data_type"] in FREE_TEXT_TYPES
            and c["column_name"] in ("filename", "ind_case_id", "known_terms")],
        "code": {k: grep(p, f, repo) for k, (p, f) in CODE_GREPS.items()},
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    print(f"wrote {out / 'schema.sql'} and {out / 'evidence.json'}")
    for k in ("check_1_score_columns", "check_2_session_links", "check_3_identity_columns",
              "free_text_columns_user_can_fill"):
        print(k, json.dumps(evidence[k], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
