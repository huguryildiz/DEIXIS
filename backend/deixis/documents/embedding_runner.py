"""The built-in models' process (slice 21; Qwen3). Runs inside the built-in environment, never inside DEIXIS.

It imports only the standard library, `torch` and `transformers`. Before it says ready it checks every file of the
manifest it is given (byte count and sha256); a missing or changed file ends it with
`{"ready": false, "code": "files_do_not_match"}`. The models load from their folders with `local_files_only=True` under
`HF_HUB_OFFLINE=1` and the data directory's own `HF_HOME`, which DEIXIS sets, so nothing is fetched and nothing is
written outside the data directory. The device is the one DEIXIS names; when it is not there (MPS on a Mac without it)
the start fails with `device_unavailable` rather than running somewhere else.

Both models are used as their model cards' "Transformers usage" sections use them:
- embedding (`Qwen3-Embedding-0.6B`): left padding, the last token's hidden state, unit length; a query is written
  `Instruct: <instruction>\nQuery:<text>`, a document as it is.
- reranker (`Qwen3-Reranker-0.6B`): the card's system prompt, `<Instruct>: …\n<Query>: …\n<Document>: …`, and the
  probability of "yes" against "no" at the last position. It is loaded for each rerank request and freed after it.

Every text is counted in tokens before it is cut at the limit, and the reply names the texts that were cut.

Protocol, one JSON object per line: first `{"ready": true, "torch", "transformers", "device", "dimensions"}`; then each
request `{"id", "kind": "document" | "query", "texts": [...]}` is answered `{"id", "vectors": [<base64 float32>...],
"truncated": [<index>...]}`, and `{"id", "kind": "rerank", "query", "documents": [...]}` is answered `{"id", "scores":
[...], "truncated": [...]}`; a failed request gets `{"id", "error"}`. The process ends when its input closes. The in-use
lock DEIXIS took before starting it is an inherited descriptor, held for as long as this process lives.
"""

import argparse
import base64
import gc
import hashlib
import json
import os
import struct
import sys

EMBED_SUB_BATCH = 8  # texts per forward pass
RERANK_SUB_BATCH = 4
RERANK_SYSTEM = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the "
                 "Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
RERANK_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def check_files(model_dir, manifest):
    """The names of manifest files that are missing or differ in size or sha256."""
    wrong = []
    for item in manifest:
        path = os.path.join(model_dir, *item["name"].split("/"))
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


def encode(values):
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode("ascii")


class Models:
    def __init__(self, args):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch, self.args = torch, args
        if args.threads is not None:
            torch.set_num_threads(args.threads)
        if args.device == "mps" and not torch.backends.mps.is_available():
            raise DeviceUnavailable("MPS is not available on this computer")
        self.device = torch.device(args.device)
        folder = os.path.join(args.model_dir, "embedding")
        self.tokenizer = AutoTokenizer.from_pretrained(folder, padding_side="left", local_files_only=True)
        self.model = AutoModel.from_pretrained(folder, local_files_only=True, torch_dtype=torch.float32).to(self.device).eval()

    def embed(self, texts, kind):
        torch = self.torch
        if kind == "query":
            texts = [f"Instruct: {self.args.instruction}\nQuery:{text}" for text in texts]
        whole = self.tokenizer(texts, truncation=False)["input_ids"]
        truncated = [i for i, ids in enumerate(whole) if len(ids) > self.args.max_tokens]
        vectors = []
        with torch.no_grad():
            for start in range(0, len(texts), EMBED_SUB_BATCH):
                batch = self.tokenizer(texts[start:start + EMBED_SUB_BATCH], padding=True, truncation=True,
                                       max_length=self.args.max_tokens, return_tensors="pt").to(self.device)
                hidden = self.model(**batch).last_hidden_state
                mask = batch["attention_mask"]
                if bool((mask[:, -1].sum() == mask.shape[0]).item()):  # left padding: the last position is the last token
                    pooled = hidden[:, -1]
                else:
                    pooled = hidden[torch.arange(hidden.shape[0], device=hidden.device), mask.sum(dim=1) - 1]
                pooled = torch.nn.functional.normalize(pooled.float(), p=2, dim=1)
                vectors += [row.tolist() for row in pooled.cpu()]
        return vectors, truncated

    def rerank(self, query, documents):
        torch = self.torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        folder = os.path.join(self.args.model_dir, "reranker")
        tokenizer = AutoTokenizer.from_pretrained(folder, padding_side="left", local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(folder, local_files_only=True,
                                                     torch_dtype=torch.float32).to(self.device).eval()
        try:
            yes, no = tokenizer.convert_tokens_to_ids("yes"), tokenizer.convert_tokens_to_ids("no")
            prefix = tokenizer.encode(RERANK_SYSTEM, add_special_tokens=False)
            suffix = tokenizer.encode(RERANK_SUFFIX, add_special_tokens=False)
            room = self.args.rerank_max_tokens - len(prefix) - len(suffix)
            pairs = [f"<Instruct>: {self.args.rerank_instruction}\n<Query>: {query}\n<Document>: {document}"
                     for document in documents]
            whole = tokenizer(pairs, padding=False, truncation=False, return_attention_mask=False)["input_ids"]
            truncated = [i for i, ids in enumerate(whole) if len(ids) > room]
            scores = []
            with torch.no_grad():
                for start in range(0, len(pairs), RERANK_SUB_BATCH):
                    inputs = tokenizer(pairs[start:start + RERANK_SUB_BATCH], padding=False, truncation="longest_first",
                                       return_attention_mask=False, max_length=room)
                    inputs["input_ids"] = [prefix + ids + suffix for ids in inputs["input_ids"]]
                    inputs = tokenizer.pad(inputs, padding=True, return_tensors="pt",
                                           max_length=self.args.rerank_max_tokens).to(self.device)
                    # Only the last position's logits: the full (batch × tokens × 151k vocabulary) tensor would take
                    # gigabytes and ran the MPS device out of memory on long abstracts (17 Oct live check).
                    last = model(**inputs, logits_to_keep=1).logits[:, -1, :]
                    pair = torch.stack([last[:, no], last[:, yes]], dim=1).float()
                    scores += torch.nn.functional.log_softmax(pair, dim=1)[:, 1].exp().cpu().tolist()
            return scores, truncated
        finally:
            del model  # the reranker is held only for its request
            gc.collect()
            if self.device.type == "mps":
                torch.mps.empty_cache()


class DeviceUnavailable(Exception):
    pass


def _version(package):
    import importlib.metadata

    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--rerank-max-tokens", type=int, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--device", required=True, choices=("cpu", "mps"))
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--rerank-instruction", required=True)
    parser.add_argument("--threads", type=int)
    args = parser.parse_args()

    wrong = check_files(args.model_dir, json.loads(args.manifest))
    if wrong:
        emit({"ready": False, "code": "files_do_not_match", "error": "files do not match: " + ", ".join(wrong)})
        return 1
    try:
        models = Models(args)
        (probe,), _ = models.embed(["ready"], "document")
    except DeviceUnavailable as exc:
        emit({"ready": False, "code": "device_unavailable", "error": str(exc)})
        return 1
    except Exception as exc:  # noqa: BLE001 - reported to DEIXIS as the reason the model is unavailable
        emit({"ready": False, "code": "load_failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        return 1
    emit({"ready": True, "torch": _version("torch"), "transformers": _version("transformers"), "device": args.device,
          "dimensions": len(probe)})

    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            if request["kind"] == "rerank":
                scores, truncated = models.rerank(str(request["query"]), [str(d) for d in request["documents"]])
                emit({"id": request_id, "scores": scores, "truncated": truncated})
            else:
                vectors, truncated = models.embed([str(text) for text in request["texts"]], request["kind"])
                emit({"id": request_id, "vectors": [encode(v) for v in vectors], "truncated": truncated})
        except Exception as exc:  # noqa: BLE001 - one failed request is answered, the process goes on
            emit({"id": request_id, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
