# Editing Helper

**Desktop app:** See [desktop/README.md](desktop/README.md) to launch the floating frontend and test it without a model.

API for the Editing Helper desktop companion. It returns model-generated editing advice from a local model or Groq.

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
- `POST /v1/coach` takes `{"question":"..."}` as JSON. A successful reply is `{"answer":"..."}`. Render the answer as plain text.
- A missing or invalid hosted access token returns `401`. Invalid input returns `422`, a busy coach returns `429`, an unavailable provider or model returns `503`, a model timeout returns `504`, and other upstream failures return `502`. Errors contain a `detail` field.

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/v1/coach \
  -H 'Content-Type: application/json' \
  -d '{"question":"Reply with hello."}'
```

## Model and scope

Change `COACH_MODEL` in the server's environment and restart to try a different already-installed local model. Local development defaults to Ollama and accepts `localhost` and `127.0.0.1`. Keep local services bound to loopback and leave `COACH_ACCESS_TOKEN` unset for token-free use. The offline launcher uses llama.cpp.

## Deploy on Northflank

Build the root `Dockerfile` in your Northflank service and expose container port `8000` as public HTTP. Use the service's HTTPS URL in the desktop app. [Northflank port configuration](https://northflank.com/docs/v1/application/network/configure-ports)

Set these runtime environment variables:

| Variable | Value |
| --- | --- |
| `COACH_PROVIDER` | `groq` |
| `COACH_MODEL` | A [Groq chat model ID](https://console.groq.com/docs/api-reference#chat-create), for example `llama-3.3-70b-versatile` |
| `GROQ_API_KEY` | Your Groq API key, injected as a server secret |
| `COACH_ACCESS_TOKEN` | A separate shared secret for desktop clients. Generate one with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. |
| `COACH_ALLOWED_HOSTS` | Comma-separated hostnames without schemes or ports, including your Northflank hostname, any custom domain, and `127.0.0.1` for the probe below |

Groq and the production container require `COACH_ACCESS_TOKEN` at startup. For a hosted deployment outside Docker, `COACH_REQUIRE_AUTH=1` also makes the token mandatory with either local provider. Setting `COACH_ACCESS_TOKEN` protects `/v1/coach` with every provider.

Use a Northflank command health check to probe the loopback address. [Northflank health-check configuration](https://northflank.com/docs/v1/application/observe/configure-health-checks)

```bash
python -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1:8000/health", timeout=2).close()'
```

To connect Electron, set `EDITING_HELPER_API` to the HTTPS service URL and `EDITING_HELPER_ACCESS_TOKEN` to the server's `COACH_ACCESS_TOKEN` in the environment that launches Electron. See [desktop setup](desktop/README.md#connect-to-a-hosted-backend).

## Backend tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests use simulated Ollama, llama.cpp, and Groq responses and cover access tokens, allowed hosts, and public health checks.

## Local desktop build and training

- Existing frontend clients still work. Optional `editor` and `version` fields let a new client include the user's selected editor without changing the response.
- The default development runner above is Ollama. The offline release path uses [llama.cpp](https://github.com/ggml-org/llama.cpp) with the same API and a pinned GGUF, without an Ollama account. Review [Ollama's eligibility terms](https://ollama.com/terms) before using its services.
- See [training/README.md](training/README.md) to start a free-GPU smoke run, export and compare weights, and launch the actual desktop frontend. This branch provides a launcher, not an installer; the desktop frontend and checkpoint are separate inputs.
