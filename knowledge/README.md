# Editing Helper knowledge base (RAG)

This is a reviewed-notes index, not a model fine-tuning dataset or a forum scraper. It adds editor-specific reference context to the existing Gemini / Groq / local-model API using SQLite FTS5, which requires no new paid service.

## Current coverage

- **DaVinci Resolve 20**: 7 short original notes with official Blackmagic Design links (Dynamic Zoom, animation, stabilization, color, Fusion, export and audio).
- **Kdenlive 26.08**: 7 short original notes with official Kdenlive manual links (cutting, transforms, position/zoom compatibility, effects, animation, glitch effects and timeline tools).
- **The other nine selectable editors**: no notes yet; Gemini can still answer, but those answers are not grounded in this knowledge index.

Source-checked means a documentation source was inspected, **not** that every step was executed inside the editor. The notes are original paraphrases rather than copied manuals.

## Add forum discussions or official documents

1. Find a real editing problem and relevant official documentation. Use community forum solutions as supplementary material.
2. Check the source's terms and any applicable permission or license. A public webpage does not automatically permit bulk scraping, redistributing text, or training a model on it. Do not add personal information, entire forum threads, private posts or copied tutorial chapters.
3. Write your **own concise summary** of the actual technique, version applicability, limitations, and important controls. Link to the original source.
4. Add one JSON object per line to a file inside knowledge/sources/. Use this schema:

~~~json
{
  "id": "kdenlive-example-note",
  "editor": "Kdenlive",
  "version": "26.08",
  "title": "An original descriptive title",
  "keywords": ["glitch", "minecraft", "keyframe", "cut"],
  "note": "Your own reviewed original summary of the solution goes here. Include practical steps and limitations.",
  "source_url": "https://example.org/original-thread",
  "source_kind": "community",
  "review_status": "needs_review",
  "rights_basis": "original_paraphrase"
}
~~~

This is a template, **not a real sourced tutorial**. Set review_status to source_checked only after verifying the reference and rights. Entries still marked needs_review are deliberately excluded from the search index.

5. From the repository root, validate and preview retrieval:

~~~bash
python3 knowledge_rag.py validate
python3 knowledge_rag.py build
python3 knowledge_rag.py search --editor Kdenlive --version 26.08 "How do I add a broken TV glitch?"
~~~

6. Test an answer in the actual editor, compare against the cited reference, and fix or remove incorrect guidance.
7. Commit the JSONL and Python changes. Do not commit knowledge/index.sqlite3; Docker generates it when redeploying.

## Northflank deployment

The root Dockerfile builds the SQLite index from the approved notes before starting FastAPI. The image enables retrieval with COACH_RAG_ENABLED=1, so no new API keys or hosted database are required.

Optional environment settings:

- COACH_RAG_ENABLED=0 disables retrieval.
- COACH_RAG_ENABLED=1 requires a prebuilt index. Locally, run python3 knowledge_rag.py build first.
- COACH_KNOWLEDGE_DB=/path/to/index.sqlite3 overrides the index path.

Keep your existing COACH_PROVIDER, COACH_MODEL, GEMINI_API_KEY, COACH_ACCESS_TOKEN and COACH_ALLOWED_HOSTS values. Do not store secrets in source notes.

## How the AI uses this

For each question, the backend searches the local index by selected editor and version, retrieves up to three relevant notes, and sends them to the model labeled **untrusted reference data**. The model is instructed to avoid invented controls and irrelevant suggestions for stylized/game footage. Optional source metadata is returned to the desktop, which offers links to the original documentation.

No matching notes means no fabricated citations; the AI can still answer without references. Version-incompatible Kdenlive or DaVinci Resolve notes are excluded instead of silently reused.

## Limits

FTS5 keyword matching is an affordable starting point; it is not guaranteed to understand synonyms, source quality or every question. The 14 notes are only a seed set. Audit accuracy in the target editor and compare answers with and without RAG before scaling. Screen analysis, clip/video uploads, conversation memory and automatic forum importing are separate future capabilities.
