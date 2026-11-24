# Editing Helper — organized documentation and forum knowledge

The AI uses an offline SQLite FTS5 index built from **original, short, source-attributed notes and document links**. It never needs to download an entire forum at question time. The selected editor is an exact search filter; version tags prevent known-incompatible notes from being used as evidence.

## Coverage snapshot — November 24, 2026

| Editing software | All records | Source-reviewed notes | Link-only references |
| --- | ---: | ---: | ---: |
| Adobe Premiere Pro | 843 | 3 | 840 |
| DaVinci Resolve | 245 | 7 | 238 |
| Kdenlive | 593 | 7 | 586 |
| Shotcut | 317 | 4 | 313 |
| CapCut | 136 | 5 | 131 |
| ACDSee Luxea | 116 | 5 | 111 |
| Lightworks | 82 | 3 | 79 |
| Clipchamp | 180 | 4 | 176 |
| OpenShot | 296 | 6 | 290 |
| Canva | 45 | 5 | 40 |
| iMovie (Mac, iOS, iPadOS references) | 213 | 6 | 207 |
| **Total** | **3,066** | **55** | **3,011** |

**Do not treat these as 3,066 verified tutorials.** The 55 source-reviewed notes are original concise paraphrases of individual techniques; they have NOT all been physically executed in their editors. The 3,011 link-only records are a searchable, editor-specific *directory* of relevant official guides or public forum discussions, not extracted article bodies or proofs of particular steps. This split prevents a forum title from becoming a false instruction.

The 1,689 supplemental additions are cataloged in `knowledge/sources/<editor>/supplemental-links.jsonl`; every editor has one such file. **Thirty duplicate OpenShot URLs were excluded** after normalizing manual aliases, tracking parameters and path variants. Section anchors and individual PDF page anchors are retained when they identify distinct material within a longer manual. The supplemental entries are link-only, not source-reviewed instructions. iMovie additions include Mac, iPhone, and iPad links with platform notes, not interchangeable interface guidance.

The source index covers **all 11 editors**. Coverage varies widely by vendor, and the count is a snapshot—not a claim that every available page or forum was found.

## Storage structure

```text
knowledge/
  sources/
    resolve20.jsonl                # reviewed DaVinci Resolve 20 summaries
    kdenlive26.jsonl               # reviewed Kdenlive 26.08 summaries
    premiere-pro/
      supplemental-links.jsonl       # additional deduplicated source references
      official-links.jsonl
      community-links.jsonl
      reviewed-notes.jsonl
    davinci-resolve/
      official-links.jsonl
      community-links.jsonl
    kdenlive/
      official-links.jsonl
      community-links.jsonl
    shotcut/
      documentation-links.jsonl   # official links + community-hosted docs
      reviewed-notes.jsonl
    capcut/
      official-links.jsonl
      reviewed-notes.jsonl
    luxea/
      official-links.jsonl
      community-links.jsonl
      reviewed-notes.jsonl
    lightworks/
      official-links.jsonl
      community-links.jsonl
      reviewed-notes.jsonl
    clipchamp/
      official-links.jsonl
      reviewed-notes.jsonl
    openshot/
      official-links.jsonl
      reviewed-notes.jsonl
    canva/
      official-links.jsonl
      reviewed-notes.jsonl
    imovie/
      official-links.jsonl
      reviewed-notes.jsonl
  index.sqlite3                     # generated, not committed
```

Every record also has a **category** such as timeline, keyframes, effects, transitions, audio, color, captions, export, performance, media or troubleshooting. Files are sorted by category and then title wherever possible. The index stores editor, version, category, title, keywords, note, source URL, kind (official/community), and review status.

### Evidence levels

- `source_checked`: An original paraphrase grounded in an inspected source. It can be supplied as an answer reference when relevant; it is **not** a claim that we tested the editor UI.
- `link_checked`: A catalog entry from source-link discovery. It helps the AI locate related documentation, **but must never be used as proof of specific buttons or steps**.
- `needs_review`: Newly added or unchecked material. The indexer **excludes** these records until reviewed.

Sources are **not** copied or mirrored in full. Forum posts may be inaccurate, outdated, contradictory, subject to access terms, or contain personal information. Link indexing does not grant permission to reproduce thread bodies or train on them.

Each editor subdirectory also contains a `supplemental-links.jsonl` catalog. Links were deduplicated against the snapshot before import and against other incoming links. These are URL/section records rather than guaranteed distinct full documents: for example, two DaVinci Resolve PDF page anchors can lead to different sections of one PDF.

## Explore and rebuild the index

From the repository root:

```bash
python3 knowledge_rag.py validate
python3 knowledge_rag.py stats
python3 knowledge_rag.py build

python3 knowledge_rag.py search --editor Kdenlive --version 26.08 "Broken TV glitch"
python3 knowledge_rag.py search --editor "Adobe Premiere Pro" "How do I animate a zoom?"
python3 knowledge_rag.py search --editor "ACDSee Luxea" --version 8 "Chroma Key"
python3 -m unittest discover -s tests -v
```

The search command returns the original URL, category, source type, version, and evidence level. The desktop displays "Source-reviewed notes" and "Further reading (links only)" separately.

## Adding new articles, forum solutions, or versions

1. Find an **actual source**. Prefer current official manuals for control names and UI steps; check community discussions for workarounds and observed failures.
2. Verify the page and its editor/version. Check permission or licensing conditions. Do not paste entire manuals, transcripts, forum conversations, emails, or personal details into the repository.
3. Write your **own short summary**, recording what the source actually supports. Mark it `needs_review` until checked. Use `link_checked` for navigation metadata that does not establish the steps.
4. Add an entry to that editor's JSONL file, with these fields:

```json
{
  "id": "kdenlive-example-minecraft-zoom",
  "editor": "Kdenlive",
  "version": "26.08",
  "category": "keyframes",
  "title": "Example: animating a zoom with Transform",
  "keywords": ["transform", "zoom", "minecraft", "keyframe"],
  "note": "An original, 30+ character summary based on the actual source goes here. Check that version and its controls before review.",
  "source_url": "https://example.org/replace-with-a-real-document",
  "source_kind": "community",
  "review_status": "needs_review",
  "rights_basis": "original_paraphrase"
}
```

   This example is **not** a real sourced note. `version: "*"` means the document is not pinned to a version, **not** that its instructions are known to work in every release.

5. Run `python3 knowledge_rag.py validate`, `stats`, `build`, and editor-specific `search` commands. Verify the source-checked entries in the target editor when possible; remove or update any false steps.
6. Commit JSONL changes (not the generated SQLite file), merge, and redeploy Northflank. The Docker build automatically regenerates the index. No paid embedding API or vector database is needed.

## Retrieval and safety

The API retrieves at most three results for a question. It favors source-reviewed, editor-compatible notes while deduplicating source URLs. Link-only entries are supplied as **further reading**, not procedural proof. Kdenlive knowledge is never mixed into Resolve prompts; inappropriate versions are rejected for version-pinned notes. Forum excerpts are not embedded as model instructions.

The desktop displays official/community labels and opens only user-clicked HTTPS source links through Electron's native bridge. Answers without matching sources still use Gemini, but must not claim that a reference was found.

## Important limits

- The knowledge system uses lexical FTS5 search, not semantic embeddings. Synonyms, jargon and long natural-language queries can miss relevant entries.
- The 55 source-reviewed notes do not cover every editor feature. The 1,322 catalog links are discoverable sources, not detailed instructions.
- Original documentation may change; these records should be reviewed periodically against the publisher's current version.
- User screen analysis, clip analysis, conversation memory, automatic forum crawling, and physically verified tutorials are separate future functionality.
