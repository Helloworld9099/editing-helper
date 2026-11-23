"""Experimental text-only Qwen3.5 4B LoRA; not an Ollama training command."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re

from common import DATA, prompt, read, validate

BASE = "Qwen/Qwen3.5-4B"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train", type=Path, default=DATA / "train.jsonl")
    p.add_argument("--holdout", type=Path, default=DATA / "holdout.jsonl")
    p.add_argument("--check", action="store_true")
    p.add_argument("--steps", type=int, default=3)
    p.add_argument("--output", type=Path)
    p.add_argument("--revision", help="Exact Hugging Face base-model commit SHA")
    p.add_argument("--export-gguf", action="store_true")
    args = p.parse_args()
    training, holdout = read(args.train), read(args.holdout, holdout=True)
    validate(training, holdout)
    print(f"Validated {len(training)} training / {len(holdout)} held-out cases.")
    if args.check:
        return
    if not args.output or not args.revision or not re.fullmatch("[0-9a-f]{40}", args.revision):
        p.error("For a real run, specify --output and a 40-character --revision.")
    if args.output.exists() or args.steps < 1:
        p.error("Use a fresh output directory and positive step count.")
    from unsloth import FastLanguageModel
    from datasets import Dataset
    import torch
    from trl import SFTConfig, SFTTrainer
    from unsloth.chat_templates import train_on_responses_only
    if not torch.cuda.is_available():
        p.error("Use a GPU runtime. This recipe is not configured for CPU training.")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE, revision=args.revision, max_seq_length=1024,
        load_in_4bit=False, load_in_16bit=True, full_finetuning=False,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=8, target_modules=["q_proj", "v_proj"], lora_alpha=8,
        lora_dropout=0, bias="none", use_gradient_checkpointing="unsloth",
        random_state=3407, max_seq_length=1024,
    )
    encoded = []
    for row in training:
        chat = [{"role": "user", "content": prompt(row["question"])},
                {"role": "assistant", "content": row["answer"]}]
        rendered = tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=False)
        if len(tokenizer(rendered, add_special_tokens=False).input_ids) > 1024:
            raise ValueError(f"{row['id']} exceeds the sequence budget.")
        encoded.append({"text": rendered})
    args.output.mkdir(parents=True, exist_ok=False)
    trainer = SFTTrainer(model=model, processing_class=tokenizer,
        train_dataset=Dataset.from_list(encoded), args=SFTConfig(
            max_length=1024, dataset_text_field="text", per_device_train_batch_size=1,
            gradient_accumulation_steps=2, max_steps=args.steps, learning_rate=1e-4,
            optim="adamw_8bit", report_to="none", save_strategy="no",
            output_dir=str(args.output / "work"),
            seed=3407, logging_steps=1, packing=False,
        ))
    trainer = train_on_responses_only(
        trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n",
    )
    if len(trainer.train_dataset) != len(training) or any(
        not any(label != -100 for label in row["labels"]) for row in trainer.train_dataset
    ):
        raise ValueError("Assistant masking failed. Check the model's chat template.")
    trainer.train()
    model.save_pretrained(args.output / "adapter")
    tokenizer.save_pretrained(args.output / "adapter")
    manifest = {"base_model": BASE, "revision": args.revision, "steps": args.steps,
                "training_sha256": hashlib.sha256(args.train.read_bytes()).hexdigest(),
                "holdout_sha256": hashlib.sha256(args.holdout.read_bytes()).hexdigest(),
                "libraries": {n: importlib.metadata.version(n) for n in
                              ("unsloth", "transformers", "trl", "torch")}}
    (args.output / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.export_gguf:
        model.save_pretrained_gguf(str(args.output / "gguf"), tokenizer, quantization_method="q4_k_m")


if __name__ == "__main__":
    main()
