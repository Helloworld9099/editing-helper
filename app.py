"""Editing Helper API for local models, Groq, and Google Gemini."""
import asyncio
import json
import logging
import os
import re
import sqlite3

from knowledge_rag import SYSTEM_GUIDANCE, index_path, prompt_context, search_notes
from demo_access import DemoAccess
from quota_limits import CoachBodyLimitMiddleware, MAX_VIDEO_BYTES, VIDEO_PATH, VideoQuota
from video_analysis import ANALYSIS_FPS, OBSERVATION_GUIDANCE, RECREATION_GUIDANCE, prepare_clip
from contextlib import asynccontextmanager, contextmanager
from secrets import compare_digest

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.datastructures import UploadFile

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


class VideoRequest(CoachRequest):
    question: str = Field(default="", max_length=1000)
    editor: str = Field(min_length=1, max_length=80)
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClipObservations(BaseModel):
    effects: list[str] = Field(max_length=15, description="Short search terms for observed edit effects.")
    observations: str = Field(min_length=1, max_length=8000,
                              description="Timeline with visual evidence and confidence for each effect.")


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


def coach_reply(answer, notes):
    return CoachReply(answer=answer, sources=[
        CoachSource(id=n["id"], title=n["title"], url=n["url"],
                    editor=n["editor"], version=n["version"], source_kind=n["source_kind"],
                    review_status=n["review_status"], category=n["category"]) for n in notes
    ] or None)


def create_app(*, model=None, timeout=60.0, transport=None, provider=None, quota_store=None):
    provider = provider or os.environ.get("COACH_PROVIDER", "ollama")
    if provider not in PROVIDERS:
        raise ValueError("COACH_PROVIDER must be ollama, llama.cpp, groq, or gemini.")
    engine, url, limits = PROVIDERS[provider]
    groq = provider == "groq"
    gemini = provider == "gemini"
    hosted = groq or gemini
    auth_mode = os.environ.get("COACH_AUTH_MODE", "shared").strip()
    if auth_mode not in {"shared", "demo"}:
        raise ValueError("COACH_AUTH_MODE must be shared or demo.")
    demo_access = None
    managed_redis = None
    if auth_mode == "demo":
        if not hosted:
            raise ValueError("COACH_AUTH_MODE=demo is only supported with a hosted model provider.")
    if quota_store is None and (auth_mode == "demo" or gemini):
        redis_url = os.environ.get("COACH_REDIS_URL", "").strip()
        if redis_url or auth_mode == "demo":
            if not redis_url.startswith(("redis://", "rediss://")):
                raise ValueError("Configure COACH_REDIS_URL with a valid Redis URL for shared quotas.")
            from redis.asyncio import from_url
            managed_redis = from_url(redis_url, decode_responses=True, socket_connect_timeout=3,
                                     socket_timeout=3, health_check_interval=30)
            quota_store = managed_redis
    if auth_mode == "demo":
        demo_access = DemoAccess(quota_store)
    video_quota = VideoQuota(quota_store) if gemini else None
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
    video_model = None
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
        video_model = (os.environ.get("COACH_VIDEO_MODEL", "").strip() or model).removeprefix("models/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", video_model):
            raise ValueError("COACH_VIDEO_MODEL must be a valid Gemini model ID.")
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY is required for Gemini.")
        upstream_headers["x-goog-api-key"] = gemini_key

    access_token = os.environ.get("COACH_ACCESS_TOKEN", "").strip()
    if auth_mode == "shared" and not access_token and (hosted or os.environ.get("COACH_REQUIRE_AUTH") == "1"):
        raise ValueError("COACH_ACCESS_TOKEN is required for hosted deployments.")
    if auth_mode == "demo" and access_token:
        raise ValueError("COACH_ACCESS_TOKEN must be unset for guest demo mode.")
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

    @contextmanager
    def model_errors(*, video=False):
        try:
            yield
        except (httpx.TimeoutException, TimeoutError):
            raise HTTPException(504, f"{engine} took too long to reply.") from None
        except httpx.ConnectError:
            raise HTTPException(503, f"Could not reach {engine}. Is it running?") from None
        except httpx.HTTPStatusError as err:
            if err.response.status_code == 404:
                raise HTTPException(503, f"The configured model is not available in {engine}.") from None
            if video and err.response.status_code in {429, 503}:
                raise HTTPException(503, "Gemini is at capacity. Try the video again later.",
                                    headers={"Retry-After": "60"}) from None
            raise HTTPException(502, f"{engine} could not answer this request.") from None
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            raise HTTPException(502, f"Could not read a valid reply from {engine}.") from None

    def retrieve_notes(query, editor, version, limit=3):
        if rag_enabled and editor and query:
            try:
                return search_notes(query, editor.strip(), version or "", database=knowledge_db, limit=limit)
            except sqlite3.Error:
                logging.getLogger(__name__).exception("Knowledge index search failed")
        return []

    async def generate(request, payload, *, target=url):
        reply = await request.app.state.model_client.post(target, headers=upstream_headers, json=payload)
        reply.raise_for_status()
        return reply.json()

    async def ask_gemini(request, parts, system, **config):
        if video_model.startswith(("gemini-3", "gemini-4")):
            config["thinkingConfig"] = {"thinkingLevel": "LOW"}
        elif video_model.startswith("gemini-2.5"):
            config["thinkingConfig"] = {"thinkingBudget": 512}
        result = await generate(request, {
            "contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": config,
        }, target=GEMINI_GENERATE.format(model=video_model))
        answer = gemini_answer(result)
        if not answer.strip():
            raise ValueError("Empty Gemini answer")
        return answer

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
    async def guard_video_upload(request):
        # Reject unauthorized private uploads before receiving large bodies.
        if access_token:
            await require_access_token(await bearer(request))
        if video_quota is None:
            raise HTTPException(503, "Video analysis requires a Gemini-enabled coach server.")
        if demo_access is not None:
            await demo_access.admit_video_upload(request, video_quota)

    api.add_middleware(CoachBodyLimitMiddleware,
                       video_guard=guard_video_upload,
                       guest_enabled=demo_access is None or demo_access.enabled)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @api.get("/health")
    async def health():
        # Liveness is independent of model availability.
        return {"status": "ok"}

    @api.post("/v1/coach", response_model=CoachReply, response_model_exclude_none=True,
              dependencies=[Depends(require_access_token)] if access_token else [])
    async def coach(body: CoachRequest, request: Request):
        slot = request.app.state.slot
        if slot.locked():
            raise HTTPException(429, "Coach is busy. Try again in a moment.",
                                headers={"Retry-After": "1"})
        async with slot:
            # Only validated, admitted guest requests consume the shared budget.
            # Quota checks still fail closed before any upstream model request.
            if demo_access is not None:
                await demo_access.charge(request)
            with model_errors():
                async with asyncio.timeout(timeout):
                    notes = retrieve_notes(body.question, body.editor, body.version)
                    question = body.question
                    if body.editor:
                        question = f"Editor: {body.editor.strip()}\n"
                        if body.version:
                            question += f"Version: {body.version.strip()}\n"
                        question += body.question
                    model_question = question + prompt_context(notes)
                    if gemini:
                        payload = {"contents": [{"role": "user", "parts": [{"text": model_question}]}]}
                        if auth_mode == "demo":
                            # Cap response generation for billed public endpoints.
                            payload["generationConfig"] = {"maxOutputTokens": 2048}
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
                    result = await generate(request, payload)
                    if provider == "ollama":
                        answer = result["message"]["content"]
                    elif gemini:
                        answer = gemini_answer(result)
                    else:
                        answer = result["choices"][0]["message"]["content"]
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("Empty or invalid answer")
        return coach_reply(answer, notes)

    @api.post(VIDEO_PATH, response_model=CoachReply, response_model_exclude_none=True,
              dependencies=[Depends(require_access_token)] if access_token else [])
    async def coach_video(request: Request):
        if video_quota is None:
            raise HTTPException(503, "Video analysis requires a Gemini-enabled coach server.")
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
            raise HTTPException(415, "Upload the reference video as multipart form data.")

        async with request.form(max_files=1, max_fields=3, max_part_size=8192) as form:
            video = form.get("video")
            if len(form.getlist("video")) != 1 or not isinstance(video, UploadFile) or not video.filename:
                raise HTTPException(422, "Attach an MP4, MOV or WebM video.")
            fields = [(key, value) for key, value in form.multi_items() if key != "video"]
            if len(dict(fields)) != len(fields):
                raise HTTPException(422, "Send each question, editor and version field once.")
            try:
                body = VideoRequest.model_validate(dict(fields))
            except ValidationError:
                raise HTTPException(422, "Select an editor and keep the question within 1000 characters.") from None
            data = await video.read(MAX_VIDEO_BYTES + 1)
            filename = video.filename

        slot = request.app.state.slot
        if slot.locked():
            raise HTTPException(429, "Coach is busy. Try again in a moment.", headers={"Retry-After": "1"})
        async with slot:
            # Recheck before spending CPU: another replica may have used the
            # remaining allowance while the client was uploading.
            if demo_access is not None:
                await demo_access.charge(request, video_quota, check_only=True)
            try:
                async with asyncio.timeout(25):
                    clip_parts, duration, motion, flash = await prepare_clip(data, filename)
            except TimeoutError:
                raise HTTPException(422, "The video took too long to decode. Try a smaller export.") from None
            if demo_access is not None:
                await demo_access.charge(request, video_quota)
            else:
                await video_quota.charge()

            with model_errors(video=True):
                async with asyncio.timeout(timeout):
                    findings = ClipObservations.model_validate_json(await ask_gemini(request, [
                        *clip_parts,
                        {"text": f"Clip duration: {duration:.3f}s. The selected sampling rate is "
                                 f"{ANALYSIS_FPS} frames per second.\n"
                                 f"Optional user question for visual focus: {body.question}"},
                    ], OBSERVATION_GUIDANCE, maxOutputTokens=2400, responseMimeType="application/json",
                       responseJsonSchema=ClipObservations.model_json_schema(),
                       mediaResolution="MEDIA_RESOLUTION_LOW"))
                    terms = findings.effects
                    if flash:
                        # Search for the controls used to build a white overlay. "Flash"
                        # alone also retrieves unrelated reports of flashing error screens.
                        terms = ["white solid generator opacity keyframes",
                                 *(effect for effect in terms if "flash" not in effect.casefold())]
                    notes = retrieve_notes(" ".join([*terms, body.question]), body.editor, body.version, limit=5)
                    task = json.dumps({
                        "editor": body.editor, "version": body.version, "question": body.question,
                        "clipDurationSeconds": duration, "clipFindings": findings.model_dump(),
                        "frameSamplingFps": ANALYSIS_FPS, "trackedFramingEvidence": motion,
                        "measuredWhiteFlashes": flash,
                    }, ensure_ascii=False)
                    answer = await ask_gemini(
                        request, [{"text": task + prompt_context(notes)}],
                        SYSTEM_GUIDANCE + "\n" + RECREATION_GUIDANCE, maxOutputTokens=4096,
                    )
        return coach_reply(answer, notes)

    return api


app = create_app()
