# Deployment security requirements

TolkCheck processes recordings and transcripts of asylum hearings: personal data that can include special categories (GDPR art. 9). Part of the BIO2 baseline is implemented in the application. The rest can only be met by the environment it runs in. This document lists both, per measure, so a deployment can be checked against it.

The hardened stack is `docker-compose.prod.yml` (with `deploy/` and `.env.prod.example`). `docker-compose.yml` is for local development only and must not be exposed to a network.

> BIO2 numbering follows the test plan (5.17 authentication incl. MFA, 5.18 privileged accounts). In ISO/IEC 27002:2022, on which BIO2 is based, MFA is control 8.5 and privileged access 8.2. Check against the BIO2 version in force.

## 8.24 Cryptography

| Provided by the application / prod stack | Required from the deployment |
|---|---|
| TLS terminated by Caddy (`deploy/Caddyfile`), HSTS, only port 443 (and 80 for redirect) published | **A certificate the officers' machines trust.** Let's Encrypt only works on a public DNS name; on an internal network, configure the organisation's certificate in the Caddyfile. |
| API, worker, database and Redis reachable only on the internal Docker network | **Encryption at rest of every volume** holding personal data: `postgres_data` (transcripts, flags, feedback, accounts), `uploads_data` (audio until processing ends), and all backups of these. Use disk or volume encryption (e.g. LUKS, BitLocker, encrypted cloud disks). The application deliberately does not encrypt at application level: a key kept next to the database credentials would add little. |
| Passwords hashed with bcrypt; session tokens signed (HS256) with a required `SECRET_KEY` | **Secret management:** `.env.prod` readable only by the operator account, or secrets injected from a vault. Rotating `SECRET_KEY` logs everyone out; that is the intended way to revoke all sessions at once. |
| Dependencies pinned via `uv.lock` in the image build | Regular image rebuilds for security updates of the base images and dependencies. |

Traffic between the containers on the internal network is not encrypted; that relies on the Docker host not being shared with untrusted workloads.

## 5.17 Authentication

| Provided | Required |
|---|---|
| Account lockout: 5 consecutive wrong passwords lock an account for 15 minutes (`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`) | **MFA through the organisation's SSO.** The application has no second factor of its own. Place it behind the IND identity provider (e.g. an identity-aware proxy in front of Caddy, or integration with the IdP), so only users who passed SSO with MFA reach the login page. Without that, 5.17 is not met. |
| Identical error message and bcrypt timing for unknown, locked and inactive accounts | **Per-IP rate limiting / WAF** in front of the stack. Lockout is per account and does not stop one address trying one password against many accounts. |
| Logout and deactivation revoke all tokens of the account (server-side `token_version`) | |
| Minimum password length 12 for accounts created via the CLI | |
| Session lifetime 10 hours (`ACCESS_TOKEN_EXPIRE_MINUTES`), cookie `HttpOnly`, `Secure`, `SameSite=Lax` | |

## 5.18 Accounts and privileged access

| Provided | Required |
|---|---|
| No self-registration; accounts only via the operator CLI: `create-user`, `list-users`, `deactivate-user`, `activate-user` (all audited) | **A joiner/mover/leaver procedure:** who may run the CLI, and periodic review of `list-users` against who should have access. |
| The app connects as `tolkcheck_app`, which can read and write rows but cannot create, alter or drop tables, roles or extensions (`deploy/postgres/10-app-role.sh`; verified). Schema changes only through the one-off `migrate` service as the database owner. | **Restricted access to the Docker host**, `.env.prod` and the database owner credentials. Anyone with shell access to the host can run the CLI. |
| Containers run as non-root users; no database admin UI (Adminer) in the prod stack; Redis requires a password | |
| Each user sees only their own sessions (enforced per query, covered by tests) | |

Every account has the same rights; there are no roles. That is acceptable while all users have the same task, and should be revisited if an administrator or auditor role is needed.

## 8.15 Logging

| Provided | Required |
|---|---|
| Security events on a dedicated `audit` logger: login success/failure (with reason), lockout, logout, rejected tokens, upload, start, role confirmation, opening an evaluation, attempts to open someone else's session, account changes | **Central collection** of container stdout/stderr (at least the `audit` logger) into a log system the application cannot modify. |
| No transcript or translation text in any log (guarded by a test that inspects every log call) | **A retention period** for logs set by IND policy. Audit lines contain user ids and IP addresses, which are personal data too. |
| Raw exceptions are no longer returned by the API (`error_message` stays internal) | **Monitoring/alerting** on audit events, e.g. repeated `account.locked` or `session.not_found`. |

The IP address in the audit log is taken from `X-Forwarded-For` (uvicorn `--proxy-headers`). Whether it is the officer's address or the frontend container's depends on the proxy chain; verify this after deployment.

## Retention and deletion (EIS-5)

Provided: audio is deleted when a session completes or fails; a daily job deletes sessions with their transcript, flags and feedback, plus any leftover audio, after `RETENTION_DAYS` (default 90). Run `python -m app.cli purge-expired --dry-run` in the worker container to see what it would delete.

Required: **backups must follow the same retention.** A backup kept longer than 90 days keeps the data the application has deleted (EDPB Guidelines 4/2019, par. 80–82).

## Third parties

The optional Claude feedback step sends transcript text to Anthropic's API, outside the EU. Enabling it in production requires a processing agreement and a transfer assessment. Without `ANTHROPIC_API_KEY` the pipeline still scores every pair, but sessions then end in `FAILED / LLM_ERROR`.

Model weights are downloaded from Hugging Face on first start; no hearing data is sent there.

## Checks after deployment

```bash
docker compose -f docker-compose.prod.yml ps                       # only caddy publishes ports
curl -sI https://$DOMAIN | grep -i strict-transport                # HSTS present
docker compose -f docker-compose.prod.yml exec worker python -m app.cli purge-expired --dry-run
docker compose -f docker-compose.prod.yml logs backend | grep "| audit"   # audit lines arrive
```
