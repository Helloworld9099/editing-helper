# Editing Helper

**Desktop app:** See [desktop/README.md](desktop/README.md) to launch the floating frontend and test it without a model.

API for the Editing Helper desktop companion. It returns model-generated editing advice through Ollama, llama.cpp, Groq, or Google Gemini.

## Start on Ubuntu

Requires Python 3.11+ (and its venv module), Ollama running on this computer, and the local `qwen3.5:4b` model. If you already ran that model successfully, reuse it. Otherwise, after installing Ollama, run `ollama pull qwen3.5:4b` once.

```bash
git clone https://github.com/Helloworld9099/editing-helper.git
cd editing-helper
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

If Ubuntu reports that `venv` is unavailable, install your distro's `python3-venv` package and retry. Leave the server terminal open while using the app. Stop it with Ctrl+C. Start it again with the last command from the project directory. If your old demo is already on port 8000, stop that instance first.

## Frontend contract

- `GET /health` is public on allowed hosts and returns `{"status":"ok"}` when the API process is up.
- The desktop supports AI questions for Adobe Premiere Pro, DaVinci Resolve, Kdenlive, Shotcut, CapCut, ACDSee Luxea, Lightworks, Clipchamp, OpenShot, Canva, and iMovie. This selects answer context; it does not verify or automate instructions inside those programs.
- `POST /v1/coach` takes `{"question":"..."}` as JSON. A successful reply is `{"answer":"..."}`. The desktop renders trusted-formatting-only Markdown from the returned answer.
- A missing or invalid hosted access token returns `401`. Invalid input returns `422`, a busy coach returns `429`, an unavailable provider or model returns `503`, a model timeout returns `504`, and other upstream failures return `502`. Errors contain a `detail` field.

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/v1/coach \
  -H 'Content-Type: application/json' \
  -d '{"question":"Reply with hello."}'
```

## Private development and public release

Your existing Northflank backend still works in `COACH_AUTH_MODE=shared` with `COACH_ACCESS_TOKEN`. Do **not** distribute that token. Normal desktop Settings hides both connection fields; for local developer configuration, run `EDITING_HELPER_DEV_SETTINGS=1 npm start`.

A separate public deployment now supports `COACH_AUTH_MODE=users`. In that mode, FastAPI verifies each signed-in user against Supabase Auth's `/auth/v1/user` endpoint and applies atomic Redis quotas **before** making any Gemini request. An Electron public release uses passwordless email OTP and stores only an encrypted per-user refresh token (or a temporary session if no secure keyring exists). No shared token is shipped.

**External setup is still required:** create a Supabase Auth project with custom SMTP and a numeric OTP email template, provision Redis, deploy a separate Northflank public service with its environment variables, configure GitHub Actions public release variables, then build and test the installers. The checked-in release config is intentionally blank and fails closed until configured. Windows/macOS unsigned installers require signing/notarization before a general release.

See [desktop/PUBLIC_RELEASE.md](desktop/PUBLIC_RELEASE.md) for step-by-step configuration and validation. The build-candidate workflow is `.github/workflows/build-public-installers.yml`.

## Editor knowledge base (RAG)

When enabled, Editing Helper searches an **offline-built SQLite FTS5 index** containing **3,066 editor-specific records** across all 11 supported editors: 55 short, original source-reviewed summaries plus 3,011 navigation-only links to official manuals and public community sources. A supplemental source import added 1,689 links after removing 30 canonical URL duplicates. These are **not 3,066 verified tutorials**: link-only entries point to sources but do not establish any specific editing procedure. Records are organized by editor folder, topic category, software version and source type.

The API preserves the original answer field and optionally returns a sources array with source-review level and topic. The desktop distinguishes "Source-reviewed notes" from "Further reading (links only)" with safe click-to-open HTTPS links. A source link means a relevant record was retrieved, **not** that all generated instructions have been physically verified.

For local use, build the index and explicitly enable RAG before starting FastAPI:

~~~bash
python3 knowledge_rag.py validate
python3 knowledge_rag.py stats
python3 knowledge_rag.py build
COACH_RAG_ENABLED=1 .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
~~~

Northflank builds and enables the index automatically through the root Dockerfile. No extra hosting/database accounts or embedding API are required. For adding documentation or permitted, reviewed forum summaries, see [knowledge/README.md](knowledge/README.md). The index is generated and should not be committed.

## Model and scope

Change `COACH_MODEL` in the server's environment and restart to try a different already-installed local model. Local development defaults to Ollama and accepts `localhost` and `127.0.0.1`. Keep local services bound to loopback and leave `COACH_ACCESS_TOKEN` unset for token-free use. The offline launcher uses llama.cpp.

## Deploy on Northflank

Build the root `Dockerfile` in your Northflank service and expose container port `8000` as public HTTP. Use the service's HTTPS URL in the desktop app. [Northflank port configuration](https://northflank.com/docs/v1/application/network/configure-ports)

Set the shared runtime environment variables for either hosted provider.

| Variable | Value |
| --- | --- |
| `COACH_ACCESS_TOKEN` | A separate shared secret for desktop clients. Generate one with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. |
| `COACH_ALLOWED_HOSTS` | Comma-separated hostnames without schemes or ports, including your Northflank hostname, any custom domain, and `127.0.0.1` for the probe below |

For Google Gemini, use the following provider settings.

| Variable | Value |
| --- | --- |
| `COACH_PROVIDER` | `gemini` |
| `COACH_MODEL` | Optional Gemini model ID. Leave unset to use `gemini-2.5-flash`. |
| `GEMINI_API_KEY` | Your Google Gemini API key, injected as a server secret |

The backend calls Google's [native Gemini API](https://ai.google.dev/api/generate-content). Google lists `gemini-2.5-flash` as deprecated with API access limited to existing users until December 1, 2026. If your project lacks access, set `COACH_MODEL` to a supported text-generation model available to your project. [Gemini 2.5 Flash availability](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash)

For Groq, use the following provider settings.

| Variable | Value |
| --- | --- |
| `COACH_PROVIDER` | `groq` |
| `COACH_MODEL` | A [Groq chat model ID](https://console.groq.com/docs/api-reference#chat-create), for example `llama-3.3-70b-versatile` |
| `GROQ_API_KEY` | Your Groq API key, injected as a server secret |

In the default private `COACH_AUTH_MODE=shared`, Gemini, Groq, and the production container require `COACH_ACCESS_TOKEN` at startup. A separate `COACH_AUTH_MODE=users` service instead requires verified Supabase accounts and shared Redis quotas; the old shared token is not used in this mode. For a hosted deployment outside Docker, `COACH_REQUIRE_AUTH=1` also makes the token mandatory with either local provider. Setting `COACH_ACCESS_TOKEN` protects `/v1/coach` with every provider.

[.env.example](.env.example) shows the runtime settings. When running outside Northflank, export the settings in the environment that starts Uvicorn.

Use a Northflank command health check to probe the loopback address. [Northflank health-check configuration](https://northflank.com/docs/v1/application/observe/configure-health-checks)

```bash
python -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1:8000/health", timeout=2).close()'
```

To connect Electron, set `EDITING_HELPER_API` to the HTTPS service URL and `EDITING_HELPER_ACCESS_TOKEN` to the server's `COACH_ACCESS_TOKEN` in the environment that launches Electron. See [developer setup](desktop/README.md#connection-modes). Public releases use per-user email-code sign-in rather than the shared developer token.

## Backend tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests use simulated Ollama, llama.cpp, Groq, and Gemini responses and cover access tokens, allowed hosts, public health checks, upstream errors, knowledge retrieval, and Gemini context injection.

## Local desktop build and training

- Existing frontend clients still work. Optional `editor` and `version` fields let a new client include the user's selected editor without changing the response.
- The default development runner above is Ollama. The offline release path uses [llama.cpp](https://github.com/ggml-org/llama.cpp) with the same API and a pinned GGUF, without an Ollama account. Review [Ollama's eligibility terms](https://ollama.com/terms) before using its services.
- See [training/README.md](training/README.md) to start a free-GPU smoke run, export and compare weights, and launch the actual desktop frontend. A manual GitHub Actions workflow now builds unsigned Linux, Windows, and macOS installer candidates after public service configuration. Code signing and real-device verification are still required.
