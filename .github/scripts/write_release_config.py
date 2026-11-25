"""Generate non-secret public desktop connection configuration during release builds."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def https_origin(name: str) -> str:
    url = os.environ.get(name, "").strip()
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or parsed.port not in (None, 443)):
        raise SystemExit(f"{name} must be an HTTPS origin with no paths, credentials, or query.")
    return url.rstrip("/")


if __name__ == "__main__":
    api_url = https_origin("PUBLIC_API_URL")
    supabase_url = https_origin("PUBLIC_SUPABASE_URL")
    key = os.environ.get("PUBLIC_SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not key.startswith("sb_publishable_") or len(key) < 20:
        raise SystemExit("PUBLIC_SUPABASE_PUBLISHABLE_KEY must be a public sb_publishable_ key, NEVER a secret/service-role key.")
    config = {"apiBaseUrl": api_url, "authentication": "user-accounts",
              "supabaseUrl": supabase_url, "supabasePublishableKey": key}
    destination = Path(__file__).resolve().parents[2] / "desktop" / "src" / "release-config.json"
    destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print("Generated public-release configuration (credentials not displayed).")
