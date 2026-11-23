# Editing Helper

Local API for the Editing Helper desktop companion. The frontend is developed separately. This version returns raw Qwen answers; it does not claim to provide verified editing instructions.

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

- `GET /health` returns `{"status":"ok"}` when the API process is up. It does not check model readiness or call Ollama.
- `POST /v1/coach` takes `{"question":"..."}` as JSON. A successful reply is `{"answer":"..."}`. Render the answer as plain text.
- `422`: invalid input; `429`: another reply is in progress; `503`: Ollama/model unavailable; `504`: model timeout; `502`: other invalid upstream result. Errors contain a `detail` field.
- The frontend requests only the API on port 8000. Port 11434 is reserved for the API's connection to Ollama.

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/v1/coach \
  -H 'Content-Type: application/json' \
  -d '{"question":"Reply with hello."}'
```

## Model and scope

Change `COACH_MODEL` in the server's environment and restart to try a different already-installed local model. No client change is needed. The API has no cloud fallback or external integrations. Use Ollama's local-only configuration if you also want to disable cloud features in Ollama itself. Keep both services bound to loopback; this version has no public authentication or hosting setup.

## Backend tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests use a fake Ollama endpoint. They validate the service contract and error handling, not Qwen's editing knowledge.
