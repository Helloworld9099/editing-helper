# Editing Helper: local Qwen training starter

Start with Kdenlive 26.08. The 10 original, documentation-grounded training
examples and 4 topic-separated holdout questions are for wiring and smoke
testing, not evidence of final quality. The answers are synthesized, not
manually walked through in Kdenlive. Source links are in [common.py](common.py).
Review examples in the actual editor and add more original training examples
before a meaningful run. Keep the holdout out of training and do not tune to
its answers. Prepare a fresh test set for the final evaluation if you use this
one to guide development.

## 1. Check the files and capture the stock baseline

From the repo root:

```bash
python3 training/train.py --check
```

With the API running on port 8000 with the stock model, run this in a second
terminal (activate the app's virtual environment first):

```bash
python training/evaluate.py --model-label stock-qwen3.5-4b --output stock.jsonl
```

Alternatively, use the stock GGUF with llama.cpp and the API below; for the
fairest comparison use the same quantization, runner and settings for both
models. Record the exact file checksum / runtime version of both candidates.
The capture script records answers and latency, not accuracy. Manually grade
each answer against its checklist in Kdenlive and keep the raw outputs.

## 2. Start an adapter smoke run on a GPU

Use a CUDA notebook/session you are eligible to use, with no paid upgrade.
Unsloth documents a free [Qwen3.5 notebook route](https://unsloth.ai/docs/models/qwen3.5/fine-tune).
Its reported ~10 GB VRAM for 4B LoRA is approximate and free GPU availability is
not guaranteed. This script isn't a CPU training recipe. Copy this private
branch into the session (a source ZIP is fine; don't paste a GitHub token or
upload private source materials into a shared notebook). Then run from its root:

```bash
python -m pip install -U unsloth
REVISION=$(python -c 'from huggingface_hub import model_info; print(model_info("Qwen/Qwen3.5-4B").sha)')
python training/train.py --revision "$REVISION" --steps 3 --output runs/smoke --export-gguf
```

Three optimizer steps are only a pipeline check. The trainer saves the adapter
and run metadata before attempting the optional GGUF export. It never starts an
Ollama training job; training uses the original model checkpoint and saves new
weights. Download the adapter, run manifest, and any GGUF file before the notebook
expires. If it cannot export or load, stop and diagnose rather than silently
shipping the base model. GGUF export and actual GPU execution have not been
verified in this branch.

## 3. Test the exported local model

Start a current [llama-server](https://github.com/ggml-org/llama.cpp/releases)
build with the exported GGUF. Select the language model GGUF, not a vision
projector. In one terminal:

```bash
llama-server -m /path/to/model.gguf --alias editing-helper-local --host 127.0.0.1 --port 8081 -c 2048 -np 1 --reasoning off --no-ui
```

In a second terminal (from the repository with the app environment active):

```bash
COACH_PROVIDER=llama.cpp COACH_MODEL=editing-helper-local python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Capture with `python training/evaluate.py --model-label tuned-qwen3.5-4b --output tuned.jsonl`.
Compare checklist pass counts and mistakes (wrong controls, wrong editor, missed
steps), not just fluency. Inspect answer truncation and validate the export's
chat template. Keep the stock model if the tuned result is worse.

## 4. Open the actual app

Stop the manually launched services above. With Claude's desktop executable
available and the app's Python environment set up:

```bash
python launch.py --runner /path/to/llama-server --model /path/to/model.gguf --sha256 YOUR_GGUF_CHECKSUM -- /path/to/EditingHelper
```

The launcher starts and checks the local runner and API, then opens the desktop
executable and cleans up its own backend processes on exit. The desktop app
must stay attached until it closes and call `http://127.0.0.1:8000` (or use
`EDITING_HELPER_API`). For a desktop app that uses a browser renderer, make
requests from its native/main process instead of enabling wide-open CORS.
The app and runtime must be packaged and tested for each supported OS separately.
Do a clean machine test offline with the exact downloadable model; record what
works and keep weights out of ordinary Git. The [base model](https://huggingface.co/Qwen/Qwen3.5-4B)
is Apache 2.0; include upstream notices and only distribute weights you have
rights to share. Keep the repo private until its owner approves public release.
