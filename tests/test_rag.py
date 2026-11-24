"""Tests for the offline SQLite editor-knowledge index and its boundaries."""
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_rag import (
    build_index, matches_version, prompt_context, read_notes,
    search_notes, source_identity, valid_url,
)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "notes.sqlite3"
        self.count = build_index(database=self.db)

    def test_all_editors_have_organized_sources_and_reviewed_notes(self):
        from knowledge_rag import SUPPORTED_EDITORS, SOURCES_DIR
        notes = read_notes()
        self.assertGreaterEqual(self.count, 3000)
        self.assertEqual(self.count, len(notes))
        self.assertEqual({note["editor"] for note in notes}, SUPPORTED_EDITORS)
        self.assertEqual({note["editor"] for note in notes if note["review_status"] == "source_checked"},
                         SUPPORTED_EDITORS)
        self.assertGreaterEqual(len([n for n in notes if n["review_status"] == "source_checked"]), 55)
        self.assertGreaterEqual(len([n for n in notes if n["review_status"] == "link_checked"]), 1000)
        self.assertTrue(all(note["rights_basis"] == "original_paraphrase" for note in notes))
        self.assertTrue(all(valid_url(note["source_url"]) for note in notes))
        self.assertTrue(all((SOURCES_DIR / n).exists() for n in ("premiere-pro", "davinci-resolve",
            "kdenlive", "shotcut", "capcut", "luxea", "lightworks", "clipchamp", "openshot", "canva", "imovie")))

    def test_glitch_retrieval_is_editor_scoped(self):
        items = search_notes("How do I make a broken TV glitch?", "Kdenlive", "26.08", database=self.db)
        self.assertTrue(items)
        self.assertEqual(items[0]["id"], "kdenlive-broken-tv")
        self.assertTrue(all(i["editor"] == "Kdenlive" for i in items))
        self.assertTrue(all(i["url"].startswith("https://") for i in items))
        self.assertFalse(any(i["editor"] == "DaVinci Resolve" for i in items))

    def test_unsupported_editor_unknown_topic_and_missing_index_return_no_refs(self):
        self.assertEqual(search_notes("glitch", "Unknown", database=self.db), [])
        self.assertEqual(search_notes("zzzxnonexistentterm", "Canva", database=self.db), [])
        self.assertEqual(search_notes("zzzxnonexistentterm", "Kdenlive", database=self.db), [])
        self.assertEqual(search_notes("glitch", "Kdenlive", database=self.db / "absent"), [])

    def test_version_filtering(self):
        self.assertTrue(matches_version("20", "20.1"))
        self.assertFalse(matches_version("20", "21"))
        self.assertFalse(matches_version("20", "200"))
        self.assertTrue(matches_version("*", "14"))
        self.assertTrue(search_notes("zoom", "DaVinci Resolve", "20.1", database=self.db))
        v21 = search_notes("zoom", "DaVinci Resolve", "21", database=self.db)
        self.assertFalse(any(n["version"] == "20" for n in v21))
        old_version = search_notes("zoom", "Kdenlive", "25.08", database=self.db)
        self.assertFalse(any(n["version"] == "26.08" for n in old_version))
        self.assertTrue(all(n["review_status"] == "link_checked" for n in old_version))

    def test_reviewed_notes_priority_and_link_only_metadata(self):
        results = search_notes("keyframe animation zoom", "OpenShot", "4.1", database=self.db, limit=5)
        self.assertTrue(results)
        self.assertEqual(results[0]["review_status"], "source_checked")
        self.assertTrue(all(r["editor"] == "OpenShot" for r in results))
        self.assertEqual(len({r["url"] for r in results}), len(results))
        context = prompt_context(results)
        self.assertIn("reference_level", context)
        if any(r["review_status"] == "link_checked" for r in results):
            self.assertIn("LINK ONLY", context)

    def test_every_editor_has_retrievable_relevant_guidance(self):
        queries = {
            "Adobe Premiere Pro": "keyframes motion animate",
            "DaVinci Resolve": "dynamic zoom",
            "Kdenlive": "transform zoom",
            "Shotcut": "glitch",
            "CapCut": "keyframes zoom",
            "ACDSee Luxea": "chroma key",
            "Lightworks": "keyframes",
            "Clipchamp": "trim",
            "OpenShot": "keyframes",
            "Canva": "video timeline",
            "iMovie": "Ken Burns",
        }
        for editor, question in queries.items():
            with self.subTest(editor=editor):
                docs = search_notes(question, editor, database=self.db)
                self.assertTrue(docs)
                self.assertTrue(all(d["editor"] == editor for d in docs))

    def test_canonical_source_identity_ignores_aliases_but_retains_sections(self):
        self.assertEqual(
            source_identity("https://www.canva.com/help/animate-designs/"),
            source_identity("https://www.canva.com/help/animate-designs"))
        self.assertEqual(
            source_identity("https://www.openshot.org/static/files/user-guide/animation.html#overview"),
            source_identity("https://cdn.openshot.org/static/files/user-guide/animation.html#overview"))
        self.assertEqual(
            source_identity("https://support.apple.com/en-ie/guide/imovie/movf8b8fc9b2/10.4.6/mac/27"),
            source_identity("https://support.apple.com/guide/imovie/movf8b8fc9b2/mac"))
        self.assertNotEqual(
            source_identity("https://documents.blackmagicdesign.com/UserManuals/Guide.pdf#page=20"),
            source_identity("https://documents.blackmagicdesign.com/UserManuals/Guide.pdf#page=21"))
        canva = search_notes("animate designs", "Canva", database=self.db, limit=5)
        self.assertEqual(len(canva), len({source_identity(d["url"]) for d in canva}))

    def test_reviewed_notes_remain_retrievable_with_hundreds_of_catalog_links(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            doc = dict(read_notes()[0])
            doc.update({"id": "reviewed-effects", "editor": "Kdenlive", "version": "*",
                        "title": "Effects controls", "keywords": ["effects"],
                        "note": "Verified effects workflow in the Kdenlive editing interface.",
                        "source_url": "https://example.com/reviewed-effects",
                        "review_status": "source_checked", "category": "effects"})
            all_docs = []
            for n in range(250):
                link = dict(doc)
                link.update({"id": f"catalog-effects-{n}", "source_url": f"https://example.com/doc-{n}",
                             "review_status": "link_checked"})
                all_docs.append(link)
            all_docs.append(doc)
            (folder / "notes.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in all_docs), encoding="utf-8")
            test_db = folder / "large.sqlite3"
            self.assertEqual(build_index(folder, test_db), 251)
            results = search_notes("effects", "Kdenlive", database=test_db)
            self.assertTrue(results)
            self.assertEqual(results[0]["id"], "reviewed-effects")
            self.assertEqual(results[0]["review_status"], "source_checked")

    def test_supplemental_import_deduplicates_sources_against_baseline(self):
        """Additional links may point into the same manual, but never at the same section."""
        import re
        from urllib.parse import parse_qsl, unquote, urlsplit

        def identity(doc):
            url = urlsplit(doc["source_url"].replace("&amp;", "&"))
            host = (url.hostname or "").lower().removeprefix("www.")
            path = re.sub(r"/+", "/", unquote(url.path)).rstrip("/") or "/"
            if host == "support.apple.com":
                path = re.sub(r"^/[a-z]{2}(?:-[a-z]{2})?/(guide/)", r"/\1", path)
                path = re.sub(r"/\d+\.\d+(?:\.\d+)?/(mac|ios|ipados)(?:/[^/]+)?$",
                              r"/\1", path)
            if host in {"openshot.org", "cdn.openshot.org"}:
                host = "openshot.org"
                path = path.replace("/static/files/user-guide/", "/files/user-guide/")
            if host == "shotcut.org":
                path = path.lower()
            query = tuple(sorted((k, v) for k, v in parse_qsl(url.query)
                                 if k.lower() not in {"_v", "fbclid", "sid", "ref"}
                                 and not k.lower().startswith("utm_")))
            fragment = (url.fragment if url.fragment
                        and not url.fragment.startswith(("main-", "top-", "_r_"))
                        else "")
            return doc["editor"], host, path, query, fragment

        entries = read_notes()
        supplemental = [e for e in entries if "-supplemental-" in e["id"]]
        baseline = {identity(e) for e in entries if "-supplemental-" not in e["id"]}
        self.assertEqual(len(supplemental), 1689)
        self.assertEqual(len(entries), 3066)
        self.assertEqual({e["editor"] for e in supplemental},
                         {e["editor"] for e in entries})
        seen = set()
        for entry in supplemental:
            key = identity(entry)
            self.assertNotIn(key, baseline, entry["source_url"])
            self.assertNotIn(key, seen, entry["source_url"])
            seen.add(key)
            self.assertEqual(entry["review_status"], "link_checked")

    def test_malicious_query_is_quoted_and_cannot_escape_fts(self):
        for query in ['" OR NOT *', 'foo*** OR Kdenlive', 'glitch ) OR (', ' AND "; DROP TABLE notes; --']:
            search_notes(query, "Kdenlive", database=self.db)
        self.assertTrue(search_notes("glitch", "Kdenlive", database=self.db))

    def test_reference_context_is_data_not_unescaped_markup(self):
        items = search_notes("zoom", "Kdenlive", "26.08", database=self.db)
        context = prompt_context(items)
        self.assertIn("RETRIEVED REFERENCE DATA", context)
        self.assertEqual(len(json.loads(context.split("\n", 3)[-1])), len(items))

    def test_invalid_or_unreviewed_notes_are_handled(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "new.jsonl"
            sample = dict(read_notes()[0])
            sample["id"] = "custom-note"
            sample["review_status"] = "needs_review"
            p.write_text(json.dumps(sample) + "\n")
            self.assertEqual(read_notes(Path(folder)), [])
            with self.assertRaisesRegex(ValueError, "No indexed"):
                build_index(Path(folder), Path(folder) / "none.sqlite3")
            sample["review_status"] = "source_checked"
            sample["source_url"] = "http://localhost/script"
            p.write_text(json.dumps(sample) + "\n")
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                read_notes(Path(folder))
            sample["source_url"] = "https://example.com/guide"
            p.write_text(json.dumps(sample) + "\n" + json.dumps(sample) + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate id"):
                read_notes(Path(folder))

    def test_bad_new_index_does_not_destroy_old_index(self):
        before = self.db.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "No reviewed"):
                build_index(Path(folder), self.db)
        self.assertEqual(self.db.read_bytes(), before)

    def test_only_https_urls_and_no_credentials(self):
        for url in ["http://example.com", "https://evil@example.com/x", "file:///etc/passwd", "https://example.com:8080/x"]:
            self.assertFalse(valid_url(url))
        self.assertTrue(valid_url("https://example.com/guide"))


if __name__ == "__main__":
    unittest.main()
