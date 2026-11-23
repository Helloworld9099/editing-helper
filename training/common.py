"""Shared seed data validation and the exact app question for Kdenlive."""
import json
from pathlib import Path

DATA = Path(__file__).parent / "data"
EDITOR = "Kdenlive"
VERSION = "26.08"
SOURCES = {
    "transform": "https://docs.kdenlive.org/en/effects_and_filters/video_effects/transform_distort_perspective/transform.html",
    "speed": "https://docs.kdenlive.org/en/cutting_and_assembling/editing.html",
    "fade_in": "https://docs.kdenlive.org/en/effects_and_filters/video_effects/motion/fade_in.html",
    "fade_out": "https://docs.kdenlive.org/en/effects_and_filters/video_effects/motion/fade_out.html",
    "cut": "https://docs.kdenlive.org/en/cutting_and_assembling/right_click_menu.html",
    "timeline": "https://docs.kdenlive.org/en/user_interface/timeline.html",
}


def read(path, holdout=False):
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        keys = {"id", "topic", "question", "source", "criteria" if holdout else "answer"}
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError(f"{path}:{n}: wrong fields.")
        for key in keys - {"criteria"}:
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"{path}:{n}: empty or invalid {key}.")
        if row["source"] not in SOURCES or len(row["question"]) > 1000:
            raise ValueError(f"{path}:{n}: invalid source or question length.")
        if holdout and (not isinstance(row["criteria"], list) or not row["criteria"] or
                        not all(isinstance(i, str) and i.strip() for i in row["criteria"])):
            raise ValueError(f"{path}:{n}: empty or invalid criteria.")
        rows.append(row)
    if not rows:
        raise ValueError(f"{path} has no examples.")
    return rows


def validate(train, holdout):
    for field in ("id", "question"):
        values = [" ".join(r[field].lower().split()) for r in train + holdout]
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate {field} within or across splits.")
    overlap = {r["topic"] for r in train} & {r["topic"] for r in holdout}
    if overlap:
        raise ValueError(f"Cross-split topic overlap: {sorted(overlap)}.")


def prompt(question):
    return f"Editor: {EDITOR}\nVersion: {VERSION}\n{question}"
