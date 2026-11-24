"""Editing Helper API for local models and hosted Groq deployments."""
import asyncio
import os
import re
from contextlib import asynccontextmanager
from secrets import compare_digest

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
LLAMA_CHAT = "http://127.0.0.1:8081/v1/chat/completions"
GROQ_CHAT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "qwen3.5:4b"
PROVIDERS = {
    "ollama": ("Ollama", OLLAMA_CHAT, {"options": {"num_predict": 512}, "think": False}),
    "llama.cpp": ("llama.cpp", LLAMA_CHAT, {"max_tokens": 512}),
    "groq": ("Groq", GROQ_CHAT, {"max_completion_tokens": 512}),
}


class CoachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    editor: str | None = Field(default=None, max_length=80)
    version: str | None = Field(default=None, max_length=40)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


class CoachReply(BaseModel):
    answer: str


def create_app(*, model=None, timeout=60.0, transport=None, provider=None):
    provider = provider or os.environ.get("COACH_PROVIDER", "ollama")
    if provider not in PROVIDERS:
        raise ValueError("COACH_PROVIDER must be ollama, llama.cpp, or groq.")
    engine, url, limits = PROVIDERS[provider]
    groq = provider == "groq"
    if model is None:
        model = os.environ.get("COACH_MODEL", "" if groq else DEFAULT_MODEL)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", model):
        raise ValueError("COACH_MODEL must be a valid model ID.")
    if not groq and re.search(
        r"(^|[:/.-])cloud($|[:/.-])", model, re.IGNORECASE
    ):
        raise ValueError("COACH_MODEL must name a local model for this provider.")

    upstream_headers = {}
    if groq:
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not groq_key:
            raise ValueError("GROQ_API_KEY is required for Groq.")
        upstream_headers["Authorization"] = f"Bearer {groq_key}"

    access_token = os.environ.get("COACH_ACCESS_TOKEN", "").strip()
    if not access_token and (groq or os.environ.get("COACH_REQUIRE_AUTH") == "1"):
        raise ValueError("COACH_ACCESS_TOKEN is required for hosted deployments.")
    if access_token and not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", access_token):
        raise ValueError("COACH_ACCESS_TOKEN must be a valid bearer token.")

    allowed_hosts = [host.strip() for host in os.environ.get(
        "COACH_ALLOWED_HOSTS", "localhost,127.0.0.1"
    ).split(",") if host.strip()]
    if not allowed_hosts:
        raise ValueError("COACH_ALLOWED_HOSTS must contain at least one host.")

    bearer = HTTPBearer(auto_error=False)

    async def require_access_token(credentials=Depends(bearer)):
        if access_token and (
            credentials is None
            or not compare_digest(credentials.credentials.encode(), access_token.encode())
        ):
            raise HTTPException(401, "A valid coach access token is required.", headers={
                "WWW-Authenticate": "Bearer",
            })

    @asynccontextmanager
    async def lifespan(api):
        api.state.slot = asyncio.Semaphore(1)
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False, timeout=timeout
        ) as client:
            api.state.model_client = client
            yield

    api = FastAPI(title="Editing Helper API", lifespan=lifespan)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @api.get("/health")
    async def health():
        # Liveness is independent of model availability.
        return {"status": "ok"}

    @api.post("/v1/coach", response_model=CoachReply,
              dependencies=[Depends(require_access_token)] if access_token else [])
    async def coach(body: CoachRequest, request: Request):
        slot = request.app.state.slot
        if slot.locked():
            raise HTTPException(429, "Coach is busy. Try again in a moment.")
        async with slot:
            try:
                async with asyncio.timeout(timeout):
                    question = body.question
                    if body.editor:
                        question = f"Editor: {body.editor.strip()}\n"
                        if body.version:
                            question += f"Version: {body.version.strip()}\n"
                        question += body.question
                    reply = await request.app.state.model_client.post(url, headers=upstream_headers, json={
                        "model": model,
                        "messages": [{"role": "user", "content": question}],
                        "stream": False,
                        **limits,
                    })
                    reply.raise_for_status()
                    result = reply.json()
                    if provider == "ollama":
                        answer = result["message"]["content"]
                    else:
                        answer = result["choices"][0]["message"]["content"]
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("Empty or invalid answer")
            except (httpx.TimeoutException, TimeoutError):
                raise HTTPException(504, f"{engine} took too long to reply.") from None
            except httpx.ConnectError:
                raise HTTPException(503, f"Could not reach {engine}. Is it running?") from None
            except httpx.HTTPStatusError as err:
                if err.response.status_code == 404:
                    raise HTTPException(503, f"The configured model is not available in {engine}.") from None
                raise HTTPException(502, f"{engine} could not answer this request.") from None
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
                raise HTTPException(502, f"Could not read a valid reply from {engine}.") from None
        return CoachReply(answer=answer)

    return api


app = create_app()
