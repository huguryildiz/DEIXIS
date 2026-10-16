"""A stand-in for `embedding_runner.py` in tests (slice 21): the same protocol and the same manifest check, no fastembed.

Vectors come from the words: each word adds 1 to one of 384 places, so texts sharing words are near each other. What
it does wrong is chosen by FAKE_RUNNER (read at start):
  ok, crash_after:N (exits after N replies), die (exits on a request), die_after:N, hang (never replies), slow_ready:S (waits S s before ready),
  slow:S (waits S s before each reply), bad_id, missing_vector, dim383, nan.
FAKE_RUNNER_LOG, when set, gets one line per request: the kind and the number of texts.
"""

import argparse
import base64
import hashlib
import json
import math
import os
import struct
import sys
import time
import zlib


def check_files(model_dir, manifest):
    wrong = []
    for item in manifest:
        path = os.path.join(model_dir, item["name"])
        try:
            data = open(path, "rb").read()
        except OSError:
            wrong.append(item["name"])
            continue
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            wrong.append(item["name"])
    return wrong


def vector(text, dimensions=384):
    values = [0.0] * dimensions
    for word in text.lower().split():
        values[zlib.crc32(word.strip(".,;:?!").encode()) % dimensions] += 1.0
    if not any(values):
        values[0] = 1.0
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def encode(values):
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode()


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir")
    parser.add_argument("--max-tokens")
    parser.add_argument("--manifest")
    parser.add_argument("--model-name")
    args = parser.parse_args()
    mode = os.environ.get("FAKE_RUNNER", "ok")
    log = os.environ.get("FAKE_RUNNER_LOG")
    wrong = check_files(args.model_dir, json.loads(args.manifest))
    if wrong:
        emit({"ready": False, "code": "files_do_not_match", "error": "files do not match: " + ", ".join(wrong)})
        return 1
    if mode.startswith("slow_ready:"):
        time.sleep(float(mode.split(":")[1]))
    emit({"ready": True, "fastembed": "fake", "onnxruntime": "fake", "dimensions": 384})
    replies = 0
    for line in sys.stdin:
        request = json.loads(line)
        if log:
            with open(log, "a") as handle:
                handle.write(f"{request['kind']} {len(request['texts'])} {os.getpid()}\n")
        if mode == "hang":
            time.sleep(3600)
        if mode == "die" or (mode.startswith("die_after:") and replies >= int(mode.split(":")[1])):
            os._exit(3)
        if mode.startswith("slow:"):
            time.sleep(float(mode.split(":")[1]))
        vectors = [vector(text) for text in request["texts"]]
        request_id = request["id"]
        if mode == "bad_id":
            request_id += 1
        if mode == "missing_vector":
            vectors = vectors[:-1]
        if mode == "dim383":
            vectors = [v[:383] for v in vectors]
        if mode == "nan":
            vectors[0][0] = float("nan")
        emit({"id": request_id, "vectors": [encode(v) for v in vectors]})
        replies += 1
        if mode.startswith("crash_after:") and replies >= int(mode.split(":")[1]):
            os._exit(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
