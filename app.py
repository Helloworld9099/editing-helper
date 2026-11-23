"""Loopback-only Editing Helper API. Start with python -m uvicorn app:app."""
import asyncio
import os
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
LLAMA_CHAT = "http://127.0.0.1:8081/v1/chat/completions"
DEFAULT_MODEL = "qwen3.5:4b"


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
    if provider not in ("ollama", "llama.cpp"):
        raise ValueError("COACH_PROVIDER must be ollama or llama.cpp.")
    engine = "Ollama" if provider == "ollama" else "llama.cpp"
    model = os.environ.get("COACH_MODEL", DEFAULT_MODEL) if model is None else model
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", model) or re.search(
        r"(^|[:/.-])cloud($|[:/.-])", model, re.IGNORECASE
    ):
        raise ValueError("COACH_MODEL must name a local Ollama model.")

    @asynccontextmanager
    async def lifespan(api):
        api.state.slot = asyncio.Semaphore(1)
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False, timeout=timeout
        ) as client:
            api.state.ollama = client
            yield

    api = FastAPI(title="Editing Helper API", lifespan=lifespan)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @api.get("/health")
    async def health():
        # Liveness only; this intentionally doesn't run or probe Ollama.
        return {"status": "ok"}

    @api.post("/v1/coach", response_model=CoachReply)
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
                    if provider == "ollama":
                        url = OLLAMA_CHAT
                        limits = {"options": {"num_predict": 512}, "think": False}
                    else:
                        url = LLAMA_CHAT
                        limits = {"max_tokens": 512}
                    reply = await request.app.state.ollama.post(url, json={
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
