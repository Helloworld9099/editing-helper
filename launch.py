"""Run the bundled local model, API and an existing desktop executable."""
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parent


def wait_ready(process, url, timeout):
    deadline = time.monotonic() + timeout
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"{url}: process exited ({process.returncode}). Check its terminal logs.")
            try:
                if client.get(url).status_code == 200 and process.poll() is None:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError(f"{url} did not become ready within {timeout}s.")


def run(args):
    model, runner = args.model.resolve(strict=True), args.runner.resolve(strict=True)
    with model.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("Expected a GGUF checkpoint.")
        if args.sha256:
            f.seek(0)
            if hashlib.file_digest(f, "sha256").hexdigest() != args.sha256.lower():
                raise ValueError("GGUF checksum mismatch.")
    frontend = Path(args.frontend[0]).resolve(strict=True)
    for port in (8000, 8081):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Port {port} is unavailable. Stop the old demo first.") from exc
    hosted_settings = {"COACH_ACCESS_TOKEN", "COACH_REQUIRE_AUTH", "COACH_ALLOWED_HOSTS",
                       "EDITING_HELPER_ACCESS_TOKEN", "GROQ_API_KEY"}
    clean_env = {k: v for k, v in os.environ.items()
                 if not k.startswith("LLAMA_") and k not in hosted_settings}
    processes = []
    try:
        processes.append(subprocess.Popen([
            str(runner), "-m", str(model), "--alias", "editing-helper-local",
            "--host", "127.0.0.1", "--port", "8081", "-c", "2048", "-np", "1",
            "--reasoning", "off", "--no-ui",
        ], cwd=runner.parent, env=clean_env))
        wait_ready(processes[-1], "http://127.0.0.1:8081/health", 180)
        api_env = dict(clean_env, COACH_PROVIDER="llama.cpp", COACH_MODEL="editing-helper-local")
        processes.append(subprocess.Popen([
            sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
            "--port", "8000", "--no-proxy-headers",
        ], cwd=ROOT, env=api_env))
        wait_ready(processes[-1], "http://127.0.0.1:8000/health", 15)
        subenv = dict(clean_env, EDITING_HELPER_API="http://127.0.0.1:8000")
        processes.append(subprocess.Popen([str(frontend), *args.frontend[1:]],
                                         cwd=frontend.parent, env=subenv))
        while processes[-1].poll() is None:
            if any(p.poll() is not None for p in processes[:2]):
                raise RuntimeError("The local backend stopped. Check its terminal logs.")
            time.sleep(0.2)
        return processes[-1].returncode
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--sha256")
    parser.add_argument("frontend", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.frontend and args.frontend[0] == "--":
        args.frontend.pop(0)
    if not args.frontend:
        parser.error("Provide the existing desktop executable after --.")
    try:
        return run(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Editing Helper could not start: {exc}\n")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
