# Development

The [project README](../README.md) covers installation. This guide covers source development and testing; see the [deployment guide](../desktop/JUDGE_DEMO.md) for hosting and installer builds.

## Architecture

Electron provides the desktop interface. FastAPI validates questions, retrieves editor-specific context from a SQLite FTS5 index, and calls the configured model provider. The hosted demo uses Gemini and Redis-backed request quotas. The application does not inspect or control editing software.

| Component | Responsibility |
| --- | --- |
| `desktop/src/`, `desktop/renderer/` | Desktop windows, settings, chat, and HTTP client |
| `app.py` | API, model providers, and request admission |
| `demo_access.py`, `quota_limits.py` | Guest quotas and request-size protection |
| `knowledge_rag.py`, `knowledge/sources/` | Search index and attributed knowledge |
| `tests/`, `desktop/test/` | Backend and desktop regression tests |
| `launch.py` | Optional local llama.cpp launcher |

See the [knowledge source policy](../knowledge/README.md) for the distinction between source-reviewed summaries and link-only references. Retrieval and automated tests do not establish real-world editing accuracy. The earlier local-model training prototype is not part of the hosted product and remains in Git history.

## Desktop development

Requires Node.js 22.12+ and npm. From the repository root:

```bash
cd desktop
npm ci
npm test
npm run mock
```

In another terminal, from `desktop/`:

```bash
EDITING_HELPER_DEV_SETTINGS=1 npm start
```

Choose an editor, right-click the mascot, open Settings, and set the server address to `http://127.0.0.1:8001`. The mock returns labeled test replies without a model or access token. Use `/long`, `/slow`, and `/err` to exercise scrolling, the three-dot reply bubble, and error handling. While waiting, Send and Clear chat should be disabled, and the interface should remain responsive. Use `npm run start:normal` to diagnose floating-window issues. Developer connection fields are hidden in ordinary and packaged guest-demo modes.

## Backend development

Requires Python 3.11+. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python knowledge_rag.py validate
python knowledge_rag.py build
python -m unittest discover -s tests -v
```

For local Ollama development, start Ollama separately, download the configured model, and run the API on loopback:

```bash
ollama pull qwen3.5:4b
COACH_RAG_ENABLED=1 python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Set the developer desktop server address to `http://127.0.0.1:8000`. For a compatible local GGUF and llama.cpp executable, use:

```bash
python launch.py --runner /path/to/llama-server --model /path/to/model.gguf -- \
  "$PWD/desktop/node_modules/.bin/electron" "$PWD/desktop"
```

Hosted providers require server-side credentials and either shared-token mode or bounded guest-demo mode. See [.env.example](../.env.example). Never expose an unauthenticated local development server to the internet.

## API contract

`GET /health` reports liveness, not provider availability.

`POST /v1/coach` accepts JSON:

```json
{"question":"How do I create a smooth zoom?","editor":"DaVinci Resolve","version":"20.1"}
```

Editor and version are optional. The reply contains an `answer` string and, when available, `sources`. Questions are limited to 1,000 characters and POST bodies to 32 KiB, including streamed bodies. Private hosted deployments require a bearer token. Demo quotas reserve one model call for text; video analysis reserves two model calls and one separate video-analysis unit after validation. Independent guest upload-attempt limits and a read-only budget preflight protect media decoding. Request bodies have bounded upload time and per-process concurrency.

| Status | Meaning |
| --- | --- |
| 200 | Successful reply |
| 401 | Invalid private access token |
| 413 / 422 | Oversized or invalid input |
| 429 | Backend busy or demo quota exhausted |
| 502 | Failed or invalid upstream response |
| 503 | Model, provider, or quota service unavailable |
| 504 | Provider timeout |

## Verification

Run the backend suite above and `cd desktop && npm ci && npm test`. Optional renderer checks: install Playwright in a development virtual environment, run `python -m playwright install chromium`, then `python test/ui/ui_check.py` from `desktop/`. Renderer checks do not exercise native Electron windows.

Before distributing, manually verify:

- The welcome screen, reply indicator, chat-size presets, keyboard shortcuts, and quit menu.
- The mascot stays the same size while dragging, the chat follows without stealing focus, and both remain on screen.
- Editor and version settings persist and affect requests.
- The public build exposes no developer connection fields and sends no private credentials.
- Successful, slow, failed, and rate-limited requests display correctly; source links open only when selected.
- The installer works on clean Windows and Linux machines.

Model and Redis unit tests use simulated services. The [deployment guide](../desktop/JUDGE_DEMO.md) covers live and packaged verification.
