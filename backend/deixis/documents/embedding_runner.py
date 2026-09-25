"""The built-in embedding model's process (slice 21). Runs inside the built-in environment, never inside DEIXIS.

It imports only the standard library and `fastembed`. Before it says ready it checks every file of the manifest it is
given (byte count and sha256); a missing or changed file ends it with `{"ready": false, "code": "files_do_not_match"}`.
The model loads from the flat folder with `local_files_only=True` under `HF_HUB_OFFLINE=1` and the data directory's
own `HF_HOME`, which DEIXIS sets, so nothing is fetched and nothing is written outside the data directory. The
tokenizer cuts every text at `--max-tokens`.

Protocol, one JSON object per line: first `{"ready": true, "fastembed", "onnxruntime", "dimensions"}`; then each
request `{"id", "kind": "document" | "query", "texts": [...]}` is answered `{"id", "vectors": [<base64 float32>...]}`
or `{"id", "error"}`. The process ends when its input closes. The in-use lock DEIXIS took before starting it is an
inherited descriptor, held for as long as this process lives.
"""

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import sys


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def check_files(model_dir, manifest):
    """The names of manifest files that are missing or differ in size or sha256."""
    wrong = []
    for item in manifest:
        path = os.path.join(model_dir, item["name"])
        try:
            if os.path.getsize(path) != item["size"]:
                wrong.append(item["name"])
                continue
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                wrong.append(item["name"])
        except OSError:
            wrong.append(item["name"])
    return wrong


def _version(package):
    """An installed package's version from its metadata (standard library), without importing the package."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def encode(vector):
    return base64.b64encode(vector.astype("<f4").tobytes()).decode("ascii")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--model-name", required=True)
    args = parser.parse_args()

    wrong = check_files(args.model_dir, json.loads(args.manifest))
    if wrong:
        emit({"ready": False, "code": "files_do_not_match", "error": "files do not match: " + ", ".join(wrong)})
        return 1
    try:
        import fastembed
        from fastembed import TextEmbedding

        model = TextEmbedding(args.model_name, specific_model_path=args.model_dir, local_files_only=True)
        model.model.tokenizer.enable_truncation(max_length=args.max_tokens)
        probe = next(iter(model.embed(["ready"], batch_size=1)))
    except Exception as exc:  # noqa: BLE001 - reported to DEIXIS as the reason the model is unavailable
        emit({"ready": False, "code": "load_failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        return 1
    emit({"ready": True, "fastembed": getattr(fastembed, "__version__", None), "onnxruntime": _version("onnxruntime"),
          "dimensions": int(probe.shape[0])})

    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            texts = [str(text) for text in request["texts"]]
            embedded = model.query_embed(texts) if request["kind"] == "query" else model.embed(texts, batch_size=64)
            emit({"id": request_id, "vectors": [encode(vector) for vector in embedded]})
        except Exception as exc:  # noqa: BLE001 - one failed request is answered, the process goes on
            emit({"id": request_id, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
