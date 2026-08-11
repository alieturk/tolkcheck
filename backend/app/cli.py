"""Operator CLI — account provisioning.

There is no public signup endpoint; accounts are created out-of-band by
whoever operates the deployment.

Usage (inside the backend container):
    uv run python -m app.cli create-user someone@ind.nl
    uv run python -m app.cli create-user someone@ind.nl --generate
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys

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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
