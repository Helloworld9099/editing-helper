"""Judge-demo release configuration must never contain private credentials."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "write_release_config.py"
spec = importlib.util.spec_from_file_location("release_config", SCRIPT)
release_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_config)


class ReleaseConfigTests(unittest.TestCase):
    def test_guest_build_needs_only_url_and_excludes_all_secrets_and_email(self):
        settings = {
            "PUBLIC_API_URL": "https://demo.example.com/",
            "GEMINI_API_KEY": "should-not-be-embedded",
            "COACH_ACCESS_TOKEN": "should-not-be-embedded-either",
            "AUTH_SUPABASE_URL": "https://old-project.supabase.co",
            "PUBLIC_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_removed",
        }
        cfg = release_config.build_config(settings)
        self.assertEqual(cfg, {
            "apiBaseUrl": "https://demo.example.com",
            "authentication": "guest-demo",
        })
        for secret in settings.values():
            if secret != settings["PUBLIC_API_URL"]:
                self.assertNotIn(secret, str(cfg))

    def test_fail_closed_without_https_origin(self):
        for settings in (
            {},
            {"PUBLIC_API_URL": ""},
            {"PUBLIC_API_URL": "http://example.com"},
            {"PUBLIC_API_URL": "https://admin:password@example.com"},
            {"PUBLIC_API_URL": "https://example.com/secret"},
            {"PUBLIC_API_URL": "https://example.com?token=abc"},
            {"PUBLIC_API_URL": "https://example.com:bad"},
            {"PUBLIC_API_URL": "https://example.com:444"},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                release_config.build_config(settings)

    def test_publisher_does_not_need_account_settings(self):
        self.assertEqual(release_config.build_config({
            "PUBLIC_API_URL": "https://demo.example.com",
        })["authentication"], "guest-demo")


if __name__ == "__main__":
    unittest.main()
