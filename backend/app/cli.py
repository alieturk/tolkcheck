"""Operator CLI — account provisioning and knowledge-base management.

There is no public signup endpoint; accounts are created out-of-band by
whoever operates the deployment.

Usage (inside the backend container):
    uv run python -m app.cli create-user someone@ind.nl
    uv run python -m app.cli create-user someone@ind.nl --generate
    uv run python -m app.cli ingest-knowledge knowledge_base
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
