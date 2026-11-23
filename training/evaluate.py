"""Capture real API outputs for manual grading; this script does not score them."""
import argparse
import json
from pathlib import Path
import time

import httpx

from common import DATA, EDITOR, SOURCES, VERSION, read


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model-label", required=True, help="Label of the checkpoint actually being served")
    p.add_argument("--holdout", type=Path, default=DATA / "holdout.jsonl")
    args = p.parse_args()
    rows = read(args.holdout, holdout=True)
    with args.output.open("x", encoding="utf-8") as output, httpx.Client(
        timeout=70, trust_env=False
    ) as client:
        for row in rows:
            start = time.monotonic()
            response = client.post("http://127.0.0.1:8000/v1/coach", json={
                "editor": EDITOR, "version": VERSION, "question": row["question"],
            })
            response.raise_for_status()
            saved = dict(row, source_url=SOURCES[row["source"]], model_label=args.model_label,
                         elapsed_s=round(time.monotonic() - start, 3), answer=response.json()["answer"])
            output.write(json.dumps(saved, ensure_ascii=False) + "\n")
            output.flush()


if __name__ == "__main__":
    main()
