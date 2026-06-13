import argparse
import hashlib
import json
from pathlib import Path

try:
    from safetensors import safe_open
except ImportError as exc:
    raise SystemExit("missing dependency: install safetensors before running this check") from exc


ROOT = Path(__file__).resolve().parent
FILES = (
    "config.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.txt",
    "1_Pooling/config.json",
    "model.safetensors",
)
TOKENS = {"unk_token": "[UNK]", "sep_token": "[SEP]", "pad_token": "[PAD]", "cls_token": "[CLS]", "mask_token": "[MASK]"}
MODULES = [
    {"idx": 0, "name": "0", "path": "", "type": "sentence_transformers.models.Transformer"},
    {"idx": 1, "name": "1", "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"},
]
WEIGHTS = {
    "bert.embeddings.word_embeddings.weight": ("vocab_size", "hidden_size"),
    "bert.embeddings.position_embeddings.weight": ("max_position_embeddings", "hidden_size"),
    "bert.embeddings.token_type_embeddings.weight": ("type_vocab_size", "hidden_size"),
    "bert.pooler.dense.weight": ("hidden_size", "hidden_size"),
}
COMMERCIAL = {
    "LICENSE": "missing LICENSE file for commercial usage review",
    "MODEL_CARD.md": "missing MODEL_CARD.md with source, training data, and intended use",
    "SAFETY.md": "missing SAFETY.md with known limits, abuse cases, and monitoring plan",
}


def load_json(file):
    return json.loads((ROOT / file).read_text(encoding="utf-8"))


def vocab_lines(text):
    lines = text.split("\n")
    return lines[:-1] if lines[-1:] == [""] else lines


def sha256(file):
    digest = hashlib.sha256()
    with (ROOT / file).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expect(errors, name, got, want):
    if got != want:
        errors.append(f"{name}: expected {want!r}, got {got!r}")


def validate(skip_hash=False):
    warnings = [message for file, message in COMMERCIAL.items() if not (ROOT / file).is_file()]
    missing = [file for file in FILES if not (ROOT / file).is_file()]
    if missing:
        return [f"missing required file: {file}" for file in missing], warnings

    errors = []
    config = load_json("config.json")
    sentence = load_json("sentence_bert_config.json")
    tokenizer = load_json("tokenizer_config.json")
    special = load_json("special_tokens_map.json")
    pooling = load_json("1_Pooling/config.json")
    vocab = vocab_lines((ROOT / "vocab.txt").read_text(encoding="utf-8"))

    for name, got, want in (
        ("vocab.txt size", len(vocab), config.get("vocab_size")),
        ("tokenizer do_lower_case", tokenizer.get("do_lower_case"), True),
        ("sentence do_lower_case", sentence.get("do_lower_case"), True),
        ("max_seq_length", sentence.get("max_seq_length"), 128),
        ("pooling dimension", pooling.get("word_embedding_dimension"), config.get("hidden_size")),
        ("pooling mode", pooling.get("pooling_mode_mean_tokens"), True),
        ("modules", load_json("modules.json"), MODULES),
    ):
        expect(errors, name, got, want)

    if int(sentence.get("max_seq_length", 0)) > int(config.get("max_position_embeddings", 0)):
        errors.append("max_seq_length must not exceed max_position_embeddings")

    vocab_set = set(vocab)
    for field, token in TOKENS.items():
        expect(errors, f"tokenizer {field}", tokenizer.get(field), token)
        expect(errors, f"special_tokens_map {field}", special.get(field), token)
        if token not in vocab_set:
            errors.append(f"missing special token in vocab.txt: {token}")

    if not skip_hash:
        manifest = load_json("ASSET_MANIFEST.json") if (ROOT / "ASSET_MANIFEST.json").is_file() else {}
        expect(errors, "manifest algorithm", manifest.get("hash_algorithm"), "sha256")
        for file in FILES:
            meta = manifest.get("files", {}).get(file)
            if not meta:
                errors.append(f"manifest missing file entry: {file}")
            else:
                expect(errors, f"{file} size", (ROOT / file).stat().st_size, meta.get("size_bytes"))
                expect(errors, f"{file} sha256", sha256(file), str(meta.get("sha256", "")).lower())

    with safe_open(ROOT / "model.safetensors", framework="pt") as weights:
        names = set(weights.keys())
        for name, dims in WEIGHTS.items():
            if name not in names:
                errors.append(f"missing tensor: {name}")
            else:
                expect(errors, f"{name} shape", tuple(weights.get_tensor(name).shape), tuple(config[d] for d in dims))

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Validate local text2vec model assets.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--skip-hash", action="store_true")
    args = parser.parse_args()

    errors, warnings = validate(args.skip_hash)
    if args.strict:
        errors += [f"strict: {warning}" for warning in warnings]
    report = {"ok": not errors, "strict": args.strict, "errors": errors, "warnings": warnings}

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif errors:
        print("model assets failed validation:\n" + "\n".join(f"{i}. {e}" for i, e in enumerate(errors, 1)))
    else:
        print("model assets ok")
        if warnings:
            print("warnings:\n" + "\n".join(f"{i}. {w}" for i, w in enumerate(warnings, 1)))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
