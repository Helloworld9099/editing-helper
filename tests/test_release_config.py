"""Checks the intentionally public-only configuration in Electron builds."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "write_release_config.py"
spec = importlib.util.spec_from_file_location("release_config", SCRIPT)
release_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_config)


class ReleaseConfigTests(unittest.TestCase):
    def test_guest_build_needs_only_the_url_and_never_includes_secrets(self):
        settings = {
            "PUBLIC_RELEASE_MODE": "demo",
            "PUBLIC_API_URL": "https://public-demo.example.com/",
            "GEMINI_API_KEY": "should-never-be-included",
            "COACH_ACCESS_TOKEN": "also-never-include",
        }
        config = release_config.build_config(settings)
        self.assertEqual(config, {
            "apiBaseUrl": "https://public-demo.example.com",
            "authentication": "guest-demo", "supabaseUrl": "", "supabasePublishableKey": "",
        })
        self.assertNotIn(settings["GEMINI_API_KEY"], str(config))
        self.assertNotIn(settings["COACH_ACCESS_TOKEN"], str(config))

    def test_fail_closed_when_release_mode_or_https_url_missing(self):
        for settings in [
            {},
            {"PUBLIC_RELEASE_MODE": "demo"},
            {"PUBLIC_RELEASE_MODE": "bogus", "PUBLIC_API_URL": "https://example.com"},
            {"PUBLIC_RELEASE_MODE": "demo", "PUBLIC_API_URL": "http://example.com"},
            {"PUBLIC_RELEASE_MODE": "demo", "PUBLIC_API_URL": "https://example.com/secret"},
            {"PUBLIC_RELEASE_MODE": "demo", "PUBLIC_API_URL": "https://admin:pass@example.com"},
            {"PUBLIC_RELEASE_MODE": "demo", "PUBLIC_API_URL": "https://example.com:bad"},
        ]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                release_config.build_config(settings)

    def test_user_mode_remains_supported_but_needs_explicit_supabase_values(self):
        env = {"PUBLIC_RELEASE_MODE": "users", "PUBLIC_API_URL": "https://public.example.com"}
        with self.assertRaisesRegex(ValueError, "PUBLIC_SUPABASE_URL"):
            release_config.build_config(env)
        env["PUBLIC_SUPABASE_URL"] = "https://project.supabase.co"
        with self.assertRaisesRegex(ValueError, "PUBLIC_SUPABASE_PUBLISHABLE_KEY"):
            release_config.build_config(env)
        env["PUBLIC_SUPABASE_PUBLISHABLE_KEY"] = "sb_publishable_1234567890"
        config = release_config.build_config(env)
        self.assertEqual(config["authentication"], "user-accounts")


if __name__ == "__main__":
    unittest.main()
