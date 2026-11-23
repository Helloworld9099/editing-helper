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
DEFAULT_MODEL = "qwen3.5:4b"


class CoachRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


class CoachReply(BaseModel):
    answer: str


def create_app(*, model=None, timeout=60.0, transport=None):
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
                    reply = await request.app.state.ollama.post(OLLAMA_CHAT, json={
                        "model": model,
                        "messages": [{"role": "user", "content": body.question}],
                        "stream": False,
                        "think": False,
                        "options": {"num_predict": 512},
                    })
                    reply.raise_for_status()
                    result = reply.json()
                    answer = result["message"]["content"]
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("Empty or invalid answer")
            except (httpx.TimeoutException, TimeoutError):
                raise HTTPException(504, "Ollama took too long to reply.") from None
            except httpx.ConnectError:
                raise HTTPException(503, "Could not reach Ollama. Is it running?") from None
            except httpx.HTTPStatusError as err:
                if err.response.status_code == 404:
                    raise HTTPException(503, "The configured model is not available in Ollama.") from None
                raise HTTPException(502, "Ollama could not answer this request.") from None
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                raise HTTPException(502, "Could not read a valid reply from Ollama.") from None
        return CoachReply(answer=answer)

    return api


app = create_app()
