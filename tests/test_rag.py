"""Tests for the offline SQLite editor-knowledge index and its boundaries."""
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_rag import (
    build_index, matches_version, prompt_context, read_notes,
    search_notes, valid_url,
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
        self.assertGreaterEqual(self.count, 1100)
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
            with self.assertRaisesRegex(ValueError, "No reviewed"):
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
