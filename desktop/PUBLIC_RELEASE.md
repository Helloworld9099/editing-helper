# Editing Helper — public-release setup and safety checklist

The code supports **user-specific email-code sign-in, account authentication at FastAPI, Redis usage limits, and installer candidates**. Public access is **not live out of the box**. An ordinary user should never see or type the backend URL, a Gemini key or the old shared `COACH_ACCESS_TOKEN`.

## Architecture

```text
Desktop app ──HTTPS──> Supabase Auth (send / verify email OTP, refresh user session)
          └─HTTPS──> Public Northflank FastAPI (user JWT)
                              ├── HTTPS Supabase /auth/v1/user verifies user
                              ├── Redis atomically enforces user, IP, global quotas
                              ├── SQLite FTS5 local knowledge index
                              └── Gemini API (private server-side key)
```

A URL or a Supabase *publishable* key is not a secret; Gemini service credentials and Supabase service-role keys **must never be bundled in Electron**. All request permissions and limits are enforced on the server, not by trusting the installed app.

## 1. Create a Supabase Auth project

1. Create a new Supabase project specifically for Editing Helper, separate from Resavor or other applications.
2. In **Authentication → Providers**, enable **Email**. Enable email confirmation. Passwordless sign-in uses a six-digit code instead of a reusable password.
3. Under **Authentication → Email Templates** configure both Magic Link and confirmation/sign-up messages to show `{{ .Token }}` prominently rather than a magic-link-only `{{ .ConfirmationURL }}`. Send a real test to a non-team account.
4. **Set up custom SMTP** and verify its domain/DKIM/SPF. Supabase's built-in sender only reaches authorized organization members and is limited (currently about two messages per hour) and **cannot serve public users**.
5. Copy **Project URL** (`https://<project>.supabase.co`) and the **publishable key** (`sb_publishable_...`). A publishable key is designed to be public; **never** use `sb_secret_`, `service_role`, or a Gemini API key in release configuration.
6. Keep Auth rate limits enabled; monitor email sending abuse. Prefer sign-up CAPTCHA / additional provider controls before a large launch.

## 2. Provision shared Redis

Create a private managed Redis instance that your Northflank service can reach. Obtain its `redis://` (private network) or `rediss://` (TLS) connection URL. This is a **secret server setting** and must not be included in desktop builds or GitHub.

The public backend uses one atomic Redis Lua script for four counters: per-user minute, per-user UTC day, per-IP minute (based on server-observed address), and global UTC day. Defaults are **5 requests/minute/user, 30/day/user, 180/minute/IP, 1000/day globally**. Counters expire automatically (up to 48 hours). If Redis is down, the API fails closed instead of forwarding unmetered Gemini traffic.

Because reverse proxies may make multiple users share a gateway IP, the IP limit is intentionally generous; review your proxy configuration before tightening it. **Do not trust arbitrary client-provided X-Forwarded-For values.**

## 3. Deploy a separate public service on Northflank

Keep your existing private FastAPI service and its shared token intact. Create a **second** service from the same GitHub repository, root Dockerfile, container port `8000`, and HTTPS endpoint.

Set these **runtime environment variables** on the PUBLIC service:

| Name | Value |
|---|---|
| `COACH_PROVIDER` | `gemini` |
| `COACH_MODEL` | A Gemini text-generation model your account can currently use |
| `GEMINI_API_KEY` | Private API key, stored only as a Northflank secret |
| `COACH_AUTH_MODE` | `users` |
| `AUTH_SUPABASE_URL` | Supabase project HTTPS origin |
| `AUTH_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable key, `sb_publishable_...` |
| `COACH_REDIS_URL` | Private Redis URL |
| `COACH_ALLOWED_HOSTS` | Your **public service's** Northflank hostname without https://, plus `127.0.0.1` |
| `COACH_USER_PER_MINUTE` | `5` (adjust to your costs) |
| `COACH_USER_PER_DAY` | `30` |
| `COACH_IP_PER_MINUTE` | `180` |
| `COACH_GLOBAL_PER_DAY` | `1000` |

Do **not** set `COACH_ACCESS_TOKEN` on the PUBLIC service, and never change `COACH_AUTH_MODE` on your private service to `users` unless intentionally moving it. The public service must return 401 for requests without a valid, confirmed Supabase user token and 429 when quotas are exceeded. The `/health` endpoint remains public.

If Redis, Supabase or Gemini is unavailable, public inference must fail safely. Monitor Gemini charges and set provider spending controls externally. Quotas limit **requests**, not guaranteed Gemini token spend.

## 4. Configure the desktop public build

From the GitHub repository, go to **Settings → Secrets and variables → Actions → Variables** and create:

| GitHub Actions variable | Value |
|---|---|
| `PUBLIC_API_URL` | Public Northflank service's `https://...` origin |
| `PUBLIC_SUPABASE_URL` | Supabase Auth origin |
| `PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_...` (public key only) |

The `.github/scripts/write_release_config.py` script validates that all three are suitable for a public build and replaces the blank `desktop/src/release-config.json` **on the build runner only**. No sensitive credential is committed or embedded.

For a local, unpackaged preview of the public authentication path:

```bash
export PUBLIC_API_URL=https://YOUR-PUBLIC-SERVICE
export PUBLIC_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
export PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_YOUR_PUBLIC_KEY
python3 .github/scripts/write_release_config.py
cd desktop
npm ci
EDITING_HELPER_PUBLIC_PREVIEW=1 npm start
```

The first-run app asks for an editor, then opens an email-code sign-in window. On a secure OS keyring it remembers the individual **refresh token**, encrypted; otherwise sign-in lasts only for that run. Sessions are refreshed and rotated via Supabase. Sign-out clears the local refresh token and requests server-side revocation.

Your developer workflow remains `EDITING_HELPER_DEV_SETTINGS=1 npm start` for your *private* backend. A packaged public release ignores developer-mode overrides and the legacy saved shared token.

## 5. Create downloadable installer candidates

Open **GitHub → Actions → Build public desktop installer candidates → Run workflow**.

This workflow uses npm/Electron Builder to generate candidates for:
- **Ubuntu/Linux**: `.AppImage` and `.deb`
- **Windows**: `.exe` (NSIS installer)
- **macOS**: `.dmg`

It does **not** publish a GitHub Release or bypass platform security. Download the generated workflow artifacts only after each job passes and run the installers on actual Windows/macOS/Ubuntu machines. At launch, the release must not prompt for developer server credentials.

**Before offering downloads to general users:** arrange code signing for Windows and Apple Developer signing/notarization for macOS, verify the signing chain, test OS compatibility, provide app ownership/contact and privacy disclosures, and decide how users will receive security updates. Unsigned installers are suitable for controlled testing but not a finished trusted public release.

## 6. Required security and usability tests

- Valid email OTP signs in, calls public FastAPI and gets an answer with correct editor sources.
- Unknown, missing, expired, fabricated, anonymous or unconfirmed user tokens fail with 401.
- Request quotas return 429; Redis outage returns 503 and **does not call Gemini**.
- An unauthorized client cannot change FastAPI backend identity or send a static service token instead.
- A packaged installer contains **no** `COACH_ACCESS_TOKEN`, `GEMINI_API_KEY`, Supabase service-role key or `COACH_REDIS_URL`.
- Logging excludes user passwords, login tokens and raw editing questions unless explicitly needed and disclosed.
- Sign in → quit → restart → token refresh → sign out works on all three OSes; Linux keyring unavailable path is tested.
- Windows/macOS signing/notarization, Linux AppImage sandbox and .deb installation are tested on real devices.
- Privacy policy explains use of Supabase for email/session data, Gemini for submitted questions, provider retention, usage limits, and contact/deletion method. Do not claim nonexistent retention periods.

## Current boundaries

This is **code-ready for a configured, controlled public beta**, not a deployed downloadable app. The account provider, SMTP, Redis, public Northflank service, build variables, installer signing, and end-to-end multi-OS testing still require operator configuration. No automatic screen capture is present.
