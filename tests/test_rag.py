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

    def test_source_records_are_reviewed_paraphrases(self):
        self.assertEqual(self.count, 14)
        notes = read_notes()
        self.assertTrue(all(note["review_status"] == "source_checked" for note in notes))
        self.assertTrue(all(note["rights_basis"] == "original_paraphrase" for note in notes))
        self.assertTrue(all(valid_url(note["source_url"]) for note in notes))

    def test_glitch_retrieval_is_editor_scoped(self):
        items = search_notes("How do I make a broken TV glitch?", "Kdenlive", "26.08", database=self.db)
        self.assertTrue(items)
        self.assertEqual(items[0]["id"], "kdenlive-broken-tv")
        self.assertTrue(all(i["editor"] == "Kdenlive" for i in items))
        self.assertTrue(all(i["url"].startswith("https://") for i in items))
        self.assertFalse(any(i["editor"] == "DaVinci Resolve" for i in items))

    def test_unsupported_editors_and_unindexed_knowledge_return_no_refs(self):
        self.assertEqual(search_notes("glitch", "Unknown", database=self.db), [])
        self.assertEqual(search_notes("glitch", "Canva", database=self.db), [])
        self.assertEqual(search_notes("hello", "Kdenlive", database=self.db), [])
        self.assertEqual(search_notes("glitch", "Kdenlive", database=self.db / "absent"), [])

    def test_version_filtering(self):
        self.assertTrue(matches_version("20", "20.1"))
        self.assertFalse(matches_version("20", "21"))
        self.assertFalse(matches_version("20", "200"))
        self.assertTrue(matches_version("*", "14"))
        self.assertTrue(search_notes("zoom", "DaVinci Resolve", "20.1", database=self.db))
        self.assertEqual(search_notes("zoom", "DaVinci Resolve", "21", database=self.db), [])
        self.assertEqual(search_notes("zoom", "Kdenlive", "25.08", database=self.db), [])

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
