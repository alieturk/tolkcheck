"""Operator CLI — account provisioning and knowledge-base management.

There is no public signup endpoint; accounts are created out-of-band by
whoever operates the deployment.

Usage (inside the backend container):
    uv run python -m app.cli create-user someone@ind.nl
    uv run python -m app.cli create-user someone@ind.nl --generate
    uv run python -m app.cli ingest-knowledge knowledge_base
    uv run python -m app.cli purge-expired --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys
from pathlib import Path

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.security import hash_password


async def _create_user(email: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            print(f"Error: a user with email '{email}' already exists.", file=sys.stderr)
            raise SystemExit(1)

        user = User(email=email, hashed_password=hash_password(password))
        db.add(user)
        await db.commit()
        await db.refresh(user)

    print(f"Created user {user.email} (id={user.id})")


def create_user_command(args: argparse.Namespace) -> None:
    if args.generate:
        password = secrets.token_urlsafe(16)
        print(f"Generated password: {password}")
    else:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: passwords do not match.", file=sys.stderr)
            raise SystemExit(1)

    asyncio.run(_create_user(args.email, password))


async def _ingest_knowledge(path: Path) -> None:
    from app.services import retrieval

    if not path.exists():
        print(f"Error: '{path}' does not exist.", file=sys.stderr)
        raise SystemExit(1)

    async with AsyncSessionLocal() as db:
        summary = await retrieval.ingest_directory(db, path)

    if not summary:
        print(f"No source files found under '{path}' (expected *.md with frontmatter).")
        return
    for source_id, count in sorted(summary.items()):
        print(f"  {source_id}: {count} chunk(s)")
    print(f"Ingested {len(summary)} source(s), {sum(summary.values())} chunk(s) total.")


def ingest_knowledge_command(args: argparse.Namespace) -> None:
    asyncio.run(_ingest_knowledge(Path(args.path)))


async def _purge_expired(dry_run: bool, days: int | None) -> None:
    from app.services.retention import purge_expired

    async with AsyncSessionLocal() as db:
        result = await purge_expired(db, dry_run=dry_run, retention_days=days)
    verb = "Would delete" if dry_run else "Deleted"
    print(f"{verb} {result['sessions_deleted']} session(s) uploaded before {result['cutoff']} "
          f"({result['retention_days']} days), {result['audio_files_deleted']} audio file(s), "
          f"{result['orphan_files_deleted']} orphan file(s).")
    if result["audio_delete_failed"]:
        print(f"{result['audio_delete_failed']} audio file(s) could not be deleted; "
              "their sessions were kept and will be retried.", file=sys.stderr)


def purge_expired_command(args: argparse.Namespace) -> None:
    asyncio.run(_purge_expired(args.dry_run, args.days))


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_user_parser = subparsers.add_parser("create-user", help="Provision a new user account")
    create_user_parser.add_argument("email")
    create_user_parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a random password and print it once, instead of prompting",
    )
    create_user_parser.set_defaults(func=create_user_command)

    ingest_parser = subparsers.add_parser(
        "ingest-knowledge",
        help="(Re-)embed the curated knowledge_base/ corpus into Postgres for RAG retrieval",
    )
    ingest_parser.add_argument(
        "path", nargs="?", default="knowledge_base",
        help="Directory of *.md source files (default: knowledge_base)",
    )
    ingest_parser.set_defaults(func=ingest_knowledge_command)

    purge_parser = subparsers.add_parser(
        "purge-expired",
        help="Run the retention job now: delete sessions and audio older than RETENTION_DAYS",
    )
    purge_parser.add_argument("--dry-run", action="store_true",
                              help="Report what would be deleted without deleting anything")
    purge_parser.add_argument("--days", type=int, default=None,
                              help="Override RETENTION_DAYS for this run")
    purge_parser.set_defaults(func=purge_expired_command)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
