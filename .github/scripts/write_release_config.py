"""Build public desktop config from explicitly selected nonsecret release settings."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def https_origin(name: str, env=None) -> str:
    value = (env if env is not None else os.environ).get(name, "").strip()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and bool(parsed.hostname)
                 and not parsed.username and not parsed.password
                 and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                 and parsed.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be an HTTPS origin without credentials, paths, or query.")
    return value.rstrip("/")


def build_config(env=None):
    env = env if env is not None else os.environ
    mode = env.get("PUBLIC_RELEASE_MODE", "").strip().lower()
    if mode not in {"demo", "users"}:
        raise ValueError("PUBLIC_RELEASE_MODE must explicitly be demo or users.")
    api_url = https_origin("PUBLIC_API_URL", env)
    if mode == "demo":
        # Never include a shared bearer secret or private upstream API key.
        return {"apiBaseUrl": api_url, "authentication": "guest-demo",
                "supabaseUrl": "", "supabasePublishableKey": ""}

    supabase_url = https_origin("PUBLIC_SUPABASE_URL", env)
    key = env.get("PUBLIC_SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not key.startswith("sb_publishable_") or len(key) < 20:
        raise ValueError("PUBLIC_SUPABASE_PUBLISHABLE_KEY must be an sb_publishable_ key; never a service-role key.")
    return {"apiBaseUrl": api_url, "authentication": "user-accounts",
            "supabaseUrl": supabase_url, "supabasePublishableKey": key}


if __name__ == "__main__":
    try:
        config = build_config()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    destination = Path(__file__).resolve().parents[2] / "desktop" / "src" / "release-config.json"
    destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print("Generated", config["authentication"], "desktop config (no shared token included).")
