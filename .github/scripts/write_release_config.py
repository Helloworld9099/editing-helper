"""Write a nonsecret judge-demo connection URL for an Electron installer."""
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
    """Fail closed unless a valid publisher HTTPS address is provided."""
    env = env if env is not None else os.environ
    return {"apiBaseUrl": https_origin("PUBLIC_API_URL", env), "authentication": "guest-demo"}


if __name__ == "__main__":
    try:
        config = build_config()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    destination = Path(__file__).resolve().parents[2] / "desktop" / "src" / "release-config.json"
    destination.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print("Generated guest demo connection configuration without credentials.")
