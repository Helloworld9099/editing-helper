# Judge Demo: no login, no server settings, no shared key in Electron

This is a **controlled judge-demo distribution path**, not unrestricted free production access. The installed desktop connects to a publisher-selected HTTPS FastAPI server automatically; nobody enters a server URL, access token, Supabase account, or Gemini API key. **The Gemini API key remains on Northflank.**

A guest can inspect the public endpoint or call it outside the desktop application, so the backend **must** enforce a finite, shared quota and your Gemini provider should also have cost controls. No frontend-only limit, install ID, or embedded shared token would provide effective protection.

## 1. Create a private Redis addon (required)

In your existing Northflank project, create an **Add-on → Redis** with public access **disabled**. Use the smallest suitable resources or an existing private Redis service. Connect its private URL to the demo backend using a Northflank linked secret group, and alias the connection URL as `COACH_REDIS_URL`.

Alternatively, a managed Redis `rediss://...` URL works if your public Northflank service can reach it. Redis is **required**: guest requests fail closed when the service cannot connect, and quotas are atomic across multiple FastAPI instances.

## 2. Deploy a separate demo FastAPI service on Northflank

Do **not** change your existing private Editing Helper service or share its `COACH_ACCESS_TOKEN`.

1. Create a separate **Combined Service** named `editing-helper-demo`.
2. Connect `Helloworld9099/editing-helper`, branch `main`, build from the **root Dockerfile**.
3. Expose **container port 8000** over a publicly accessible HTTPS hostname.
4. Set these runtime environment variables on this *new* service:

| Name | Example / meaning |
|---|---|
| `COACH_PROVIDER` | `gemini` |
| `COACH_MODEL` | Gemini text model already available to your Google project (optional) |
| `GEMINI_API_KEY` | Your private Gemini key, set as a Northflank **secret**, never committed |
| `COACH_AUTH_MODE` | **`demo`** |
| `COACH_REDIS_URL` | Linked private Redis URL; set as a Northflank **secret** |
| `COACH_DEMO_GLOBAL_PER_DAY` | **`100`** (REQUIRED explicit UTC-day cap, max 1000) |
| `COACH_DEMO_GLOBAL_PER_MINUTE` | `20` (optional; default 20) |
| `COACH_DEMO_IP_PER_MINUTE` | `8` (optional; default 8) |
| `COACH_DEMO_IP_PER_DAY` | `60` (optional; default 60) |
| `COACH_ALLOWED_HOSTS` | `your-demo-hostname.example,127.0.0.1` (**no** `https://`) |

**Leave `COACH_ACCESS_TOKEN` unset on this service.** Guest demo startup rejects it, preventing accidental reuse of your private credential. No `AUTH_SUPABASE_URL`, SMTP or email login is required.

`COACH_DEMO_GLOBAL_PER_DAY` is mandatory even if the other limits are defaulted; the app refuses to start without it. The shared Redis quota reserves an IP/minute, IP/day, global/minute and global/day count together before contacting Gemini; failure to reach Redis returns 503, and exhausted quotas return 429. The quota resets with UTC-day/minute buckets (keys expire automatically). The demo limits the model response size, but request quotas **do not guarantee a precise monetary ceiling**. Monitor Gemini usage and configure Google provider cost/budget controls separately.

The IP counter uses the server-observed client address, not an arbitrary user-provided `X-Forwarded-For` header. Depending on Northflank's ingress, multiple judges may share the same observed proxy IP; if so, per-IP limits affect them together. The global caps still protect against unlimited requests. Test from outside your home network and adjust the IP limits carefully.

## 3. Verify the hosted demo endpoint

Replace the placeholders with your actual public Northflank HTTPS hostname.

```bash
curl -fsS https://YOUR-DEMO-SERVICE/health
```

Expected: `{"status":"ok"}`.

Then try a guest request:

```bash
curl -i https://YOUR-DEMO-SERVICE/v1/coach \
  -H 'Content-Type: application/json' \
  --data '{"question":"How do I create a smooth zoom?","editor":"Kdenlive"}'
```

Expected: HTTP 200 and an `answer`. No Authorization header is required. Repeat calls beyond a **temporarily lowered** IP/minute cap to confirm HTTP 429, then restore appropriate limits before judging. Disconnect Redis briefly only in a controlled test: requests must fail with 503 without spending Gemini tokens. Do not run the service without quotas.

## 4. Build and distribute the desktop application

Judges should install the prebuilt Windows or Linux package from [GitHub Releases](https://github.com/Helloworld9099/editing-helper/releases). They do not need to follow the maintainer steps below.

### Build locally (no GitHub Actions required)

From the repository root, on Ubuntu with Node.js 22.12+:

```bash
export PUBLIC_API_URL=https://p01--demo-backend--fbvcc7mvswr6.code.run
python3 .github/scripts/write_release_config.py
cd desktop
npm ci
npm test
npx --yes electron-builder@26.18.0 --linux deb --x64 --publish never
```

To build the Windows NSIS installer from the same Ubuntu checkout, with Docker installed, run from `desktop/` after generating the release config:

```bash
sudo docker run --rm \
  -v "$PWD:/project" \
  -v editing-helper-node-modules:/project/node_modules \
  -w /project \
  electronuserland/builder:wine \
  /bin/bash -c "npm ci && npx --yes electron-builder@26.18.0 --win nsis --x64 --publish never"
```

On a Windows development machine, generate the same release configuration, install npm dependencies, then run `npx --yes electron-builder@26.18.0 --win nsis --x64 --publish never` in `desktop/`.

Installers appear in `desktop/dist/`. Publish the `.deb` and `.exe` as GitHub Release assets, not regular Git commits. A blockmap is unnecessary for a manual installer download. Include SHA-256 hashes and test on clean systems before sharing.

### Optional GitHub Actions build

Run **Build judge demo installers** on `main`. The workflow defaults to the public demo hostname above; the repository variable `PUBLIC_API_URL` can override it. The workflow produces unsigned Linux, Windows and macOS candidates. It is optional and consumes the account's Actions allowance.

Never bundle the provider key, Redis URL, or private access token. The public HTTPS origin is the only deployment setting needed in the installer.

## 5. Test a no-login desktop preview locally on Ubuntu

From the repository root:

```bash
git switch main
git pull origin main
export PUBLIC_API_URL=https://YOUR-DEMO-SERVICE
python3 .github/scripts/write_release_config.py
cd desktop
npm ci
EDITING_HELPER_PUBLIC_PREVIEW=1 npm start
```

The normal app opens without an account prompt. Choose the editor and ask a question. The chat should receive an answer without server settings. The app automatically uses `PUBLIC_API_URL`.

**Important:** The preview script edits `desktop/src/release-config.json` locally, which is a tracked **public, nonsecret** file. To restore the safe checked-in placeholder after testing, return to the repository root and run:

```bash
git restore desktop/src/release-config.json
```

Don't commit a locally generated config unnecessarily.

## 6. Release gate: verify before handing judges a download

- Run `python3 -m unittest discover -s tests -v` with dependencies from `requirements.txt`.
- Run `cd desktop && npm ci && npm test`.
- Test a real guest question through FastAPI with no Authorization header.
- Confirm HTTP 429 when quotas are reached, and 503 when Redis is unavailable.
- Open the installer on a clean Ubuntu/Windows computer (and macOS if distributing a macOS build) and check **no login, no URL, no token** is requested.
- Inspect packaged files to ensure no `GEMINI_API_KEY`, `COACH_ACCESS_TOKEN` or `COACH_REDIS_URL` appears.
- Verify the editor knowledge links load and answers still show only `AI guidance` when unsourced.
- Provide a short judge README (startup, supported editors, example prompt, limitations), and arrange a trusted way to share the installer.
- Monitor usage during judging. When the evaluation finishes, stop the separate demo service entirely to disable anonymous calls.

Guest mode is simpler for judges, but cannot prevent determined abuse; stop the demo server after evaluation.
