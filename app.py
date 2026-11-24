"""Editing Helper API for local models, Groq, and Google Gemini."""
import asyncio
import logging
import os
import re
import sqlite3

from knowledge_rag import SYSTEM_GUIDANCE, index_path, prompt_context, search_notes
from public_access import PublicAccess
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
GEMINI_GENERATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
PROVIDERS = {
    "ollama": ("Ollama", OLLAMA_CHAT, {"options": {"num_predict": 512}, "think": False}),
    "llama.cpp": ("llama.cpp", LLAMA_CHAT, {"max_tokens": 512}),
    "groq": ("Groq", GROQ_CHAT, {"max_completion_tokens": 512}),
    "gemini": ("Gemini", GEMINI_GENERATE, {}),
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


class CoachSource(BaseModel):
    id: str
    title: str
    url: str
    editor: str
    version: str
    source_kind: str
    review_status: str = "link_checked"
    category: str = "general"


class CoachReply(BaseModel):
    answer: str
    sources: list[CoachSource] | None = None


def gemini_answer(result):
    parts = result["candidates"][0]["content"]["parts"]
    if not isinstance(parts, list):
        raise ValueError("Invalid Gemini content parts")
    return "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str)
    )


def create_app(*, model=None, timeout=60.0, transport=None, provider=None, quota_store=None):
    provider = provider or os.environ.get("COACH_PROVIDER", "ollama")
    if provider not in PROVIDERS:
        raise ValueError("COACH_PROVIDER must be ollama, llama.cpp, groq, or gemini.")
    engine, url, limits = PROVIDERS[provider]
    groq = provider == "groq"
    gemini = provider == "gemini"
    hosted = groq or gemini
    auth_mode = os.environ.get("COACH_AUTH_MODE", "shared").strip()
    if auth_mode not in {"shared", "users"}:
        raise ValueError("COACH_AUTH_MODE must be shared or users.")
    public_access = None
    managed_redis = None
    if auth_mode == "users":
        if quota_store is None:
            redis_url = os.environ.get("COACH_REDIS_URL", "").strip()
            if not redis_url.startswith(("redis://", "rediss://")):
                raise ValueError("COACH_REDIS_URL is required for public user quotas.")
            from redis.asyncio import from_url
            managed_redis = from_url(redis_url, decode_responses=True, socket_connect_timeout=3,
                                     socket_timeout=3, health_check_interval=30)
            quota_store = managed_redis
        public_access = PublicAccess(
            supabase_url=os.environ.get("AUTH_SUPABASE_URL", "").strip(),
            publishable_key=os.environ.get("AUTH_SUPABASE_PUBLISHABLE_KEY", "").strip(),
            redis_store=quota_store,
        )
    rag_setting = os.environ.get("COACH_RAG_ENABLED", "0").strip()
    if rag_setting not in {"0", "1"}:
        raise ValueError("COACH_RAG_ENABLED must be 0 or 1.")
    rag_enabled = rag_setting == "1"
    knowledge_db = index_path()
    if rag_enabled and not knowledge_db.is_file():
        raise ValueError("Knowledge index is missing. Run 'python knowledge_rag.py build'.")
    if model is None:
        default_model = {"groq": "", "gemini": DEFAULT_GEMINI_MODEL}.get(provider, DEFAULT_MODEL)
        model = os.environ.get("COACH_MODEL", default_model)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", model):
        raise ValueError("COACH_MODEL must be a valid model ID.")
    if not hosted and re.search(
        r"(^|[:/.-])cloud($|[:/.-])", model, re.IGNORECASE
    ):
        raise ValueError("COACH_MODEL must name a local model for this provider.")

    upstream_headers = {}
    if groq:
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not groq_key:
            raise ValueError("GROQ_API_KEY is required for Groq.")
        upstream_headers["Authorization"] = f"Bearer {groq_key}"
    elif gemini:
        model = model.removeprefix("models/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", model):
            raise ValueError("COACH_MODEL must be a valid Gemini model ID.")
        url = url.format(model=model)
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY is required for Gemini.")
        upstream_headers["x-goog-api-key"] = gemini_key

    access_token = os.environ.get("COACH_ACCESS_TOKEN", "").strip()
    if auth_mode == "shared" and not access_token and (hosted or os.environ.get("COACH_REQUIRE_AUTH") == "1"):
        raise ValueError("COACH_ACCESS_TOKEN is required for hosted deployments.")
    if access_token and not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", access_token):
        raise ValueError("COACH_ACCESS_TOKEN must be a valid bearer token.")

    allowed_hosts = [host.strip() for host in os.environ.get(
        "COACH_ALLOWED_HOSTS", "localhost,127.0.0.1"
    ).split(",") if host.strip()]
    if not allowed_hosts:
        raise ValueError("COACH_ALLOWED_HOSTS must contain at least one host.")

    bearer = HTTPBearer(auto_error=False)

    async def require_access_token(request: Request, credentials=Depends(bearer)):
        if auth_mode == "users":
            if credentials is None:
                raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
            user_id = await public_access.authenticate(
                credentials.credentials, request.app.state.model_client,
            )
            await public_access.charge(user_id, request)
            request.state.authenticated_user_id = user_id
            return
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
            try:
                yield
            finally:
                if managed_redis is not None:
                    await managed_redis.aclose()

    api = FastAPI(title="Editing Helper API", lifespan=lifespan)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @api.get("/health")
    async def health():
        # Liveness is independent of model availability.
        return {"status": "ok"}

    @api.post("/v1/coach", response_model=CoachReply, response_model_exclude_none=True,
              dependencies=[Depends(require_access_token)] if access_token or auth_mode == "users" else [])
    async def coach(body: CoachRequest, request: Request):
        slot = request.app.state.slot
        if slot.locked():
            raise HTTPException(429, "Coach is busy. Try again in a moment.")
        async with slot:
            try:
                async with asyncio.timeout(timeout):
                    notes = []
                    if rag_enabled and body.editor:
                        try:
                            notes = search_notes(body.question, body.editor.strip(),
                                                 body.version or "", database=knowledge_db)
                        except sqlite3.Error:
                            logging.getLogger(__name__).exception("Knowledge index search failed")
                            # The coach can still answer, but may not claim source support.
                    question = body.question
                    if body.editor:
                        question = f"Editor: {body.editor.strip()}\n"
                        if body.version:
                            question += f"Version: {body.version.strip()}\n"
                        question += body.question
                    model_question = question + prompt_context(notes)
                    if gemini:
                        payload = {"contents": [{"role": "user", "parts": [{"text": model_question}]}]}
                        if rag_enabled:
                            payload["systemInstruction"] = {"parts": [{"text": SYSTEM_GUIDANCE}]}
                    else:
                        messages = [{"role": "user", "content": model_question}]
                        if rag_enabled:
                            messages.insert(0, {"role": "system", "content": SYSTEM_GUIDANCE})
                        payload = {
                            "model": model,
                            "messages": messages,
                            "stream": False,
                            **limits,
                        }
                    reply = await request.app.state.model_client.post(url, headers=upstream_headers, json=payload)
                    reply.raise_for_status()
                    result = reply.json()
                    if provider == "ollama":
                        answer = result["message"]["content"]
                    elif gemini:
                        answer = gemini_answer(result)
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
        return CoachReply(answer=answer, sources=[
            CoachSource(id=n["id"], title=n["title"], url=n["url"],
                        editor=n["editor"], version=n["version"],
                        source_kind=n["source_kind"],
                        review_status=n["review_status"], category=n["category"]) for n in notes
        ] or None)

    return api


app = create_app()
