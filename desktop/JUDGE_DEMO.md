# Deployment and release

This guide is for maintainers. Judges install the prebuilt Windows or Linux package; see the [project README](../README.md).

## Hosted demo

Use a dedicated Northflank service built from the root [Dockerfile](../Dockerfile), with public HTTPS on container port 8000. The private development service and guest demo must have separate secret scopes.

Create a private Redis add-on or use a reachable managed Redis instance. Set these **runtime** environment variables on the demo service:

| Variable | Value |
| --- | --- |
| `COACH_PROVIDER` | `gemini` |
| `COACH_MODEL` | A supported Gemini text model available to the Google project |
| `GEMINI_API_KEY` | Server-side Gemini secret |
| `COACH_AUTH_MODE` | `demo` |
| `COACH_REDIS_URL` | Private Redis connection URL |
| `COACH_DEMO_GLOBAL_PER_DAY` | `100` (required; maximum 1000) |
| `COACH_DEMO_GLOBAL_PER_MINUTE` | `20` |
| `COACH_DEMO_IP_PER_MINUTE` | `8` |
| `COACH_DEMO_IP_PER_DAY` | `60` |
| `COACH_ALLOWED_HOSTS` | `p01--demo-backend--fbvcc7mvswr6.code.run,127.0.0.1` |

Do not inherit `COACH_ACCESS_TOKEN` in demo mode. Restrict private secret groups to the intended service. Keep provider keys and Redis credentials out of source, installers, and public logs. Rotate any previously committed credentials; deleting a file does not remove it from Git history.

The Docker build generates the knowledge index and runs the backend as a non-root user. The demo requires Redis and a finite daily limit, rejects requests when Redis is unavailable, and reserves minute/day quotas atomically before contacting the model. Per-IP counters use the server-observed address; users behind the same proxy may share an allowance. Daily quotas reset at UTC midnight. Request caps are not a monetary guarantee; configure provider budget controls and monitor usage.

For a separate private hosted service, use `COACH_AUTH_MODE=shared`, `COACH_ACCESS_TOKEN`, the appropriate allowed hosts, and provider secrets. See [.env.example](../.env.example). Do not expose Redis publicly.

### Verify the service

```bash
BASE=https://p01--demo-backend--fbvcc7mvswr6.code.run
curl -fsS "$BASE/health"
curl -i "$BASE/v1/coach" \
  -H 'Content-Type: application/json' \
  --data '{"question":"How do I create a smooth zoom?","editor":"Kdenlive"}'
```

Expect liveness JSON and HTTP 200 with an answer without an Authorization header. In an isolated test service with a low cap, verify HTTP 429 on quota exhaustion, HTTP 413 for oversized bodies, HTTP 422 for invalid input, and HTTP 503 during a Redis outage. Confirm rejected requests do not reach the provider.

## Build installers

From the repository root on Ubuntu, with Python and Node.js 22.12+:

```bash
export PUBLIC_API_URL=https://p01--demo-backend--fbvcc7mvswr6.code.run
python3 .github/scripts/write_release_config.py
cd desktop
npm ci
npm test
npx --yes electron-builder@26.18.0 --linux deb --x64 --publish never
```

For a Windows x64 NSIS installer from Linux, run in `desktop/` with Docker installed:

```bash
sudo docker run --rm \
  -v "$PWD:/project" \
  -v editing-helper-node-modules:/project/node_modules \
  -w /project \
  electronuserland/builder:wine \
  /bin/bash -c "npm ci && npx --yes electron-builder@26.18.0 --win nsis --x64 --publish never"
```

On Windows, generate the same release configuration and run the Windows electron-builder command directly. The optional GitHub Actions installer workflow accepts an override through the repository variable `PUBLIC_API_URL`. Local builds do not consume Actions minutes.

For an unpackaged demo preview, generate the release config and run `EDITING_HELPER_PUBLIC_PREVIEW=1 npm start` in `desktop/`. Restore the checked-in placeholder after testing with `git restore desktop/src/release-config.json` from the root. The generated configuration contains only an HTTPS origin and guest authentication mode.

## Release verification

Installers appear in `desktop/dist/`. Publish the Windows `.exe` and Linux `.deb` as GitHub Release assets, not source files. Include [SHA-256 checksums for the supplied v0.1.0 builds](../docs/releases/v0.1.0/SHA256SUMS.txt); regenerate the checksum file after rebuilding. The optional blockmap is not needed for manual installation.

The supplied Linux installer was inspected against source commit `39bc9650d407ad3f25b32cd85313bed5404cc77e`; all 15 packaged application and renderer source files matched and its public demo URL was confirmed. The supplied Windows file is an unsigned NSIS installer; its payload and installation behavior were not independently verified. Both supplied installers predate subsequent welcome-screen changes. Inspection is not a malware scan or runtime acceptance test.

Before publishing:

- Run the [development tests](../docs/DEVELOPMENT.md) and inspect packaged configuration for accidental credentials.
- Test clean Windows and Linux installations, automatic demo connection, normal use, and complete exit.
- Verify that downloaded assets match the published checksums.
- Investigate actual malware detections. Unsigned installers may trigger publisher or reputation warnings; never instruct users to disable security software. Signing and platform verification are necessary for a broader production release.
- Verify public download access and the live demo outside the development environment. Monitor usage and keep the demo available throughout judging; stop the guest service when evaluation ends.
