"""A stand-in for llama.cpp's `llama-server` in tests: the same command line, endpoints and reply shapes, no model.

Run directly (the tests write it into the runtime folder as `llama-server` with a shebang to this interpreter). It
serves GET /health (503 while "loading", then 200, no key), and with `Authorization: Bearer <--api-key>`:
POST /v1/rerank (`results[{index, relevance_score}]`), POST
/tokenize (one token per UTF-8 byte) and POST /detokenize. A rerank scores each document by the share of the query's words it holds,
times 7, minus 3: raw scores of either sign and above 1, as llama.cpp's are.

FAKE_LLAMA (comma-separated) chooses what goes wrong:
  slow_load:S (503 for S seconds), nan, wrong_count, duplicate_index, crash (exits on
  the first rerank after the probe), hang (never answers a rerank after the probe),
  reject_key (401 to every authenticated call), bind_fail:N (the first N starts say the port is taken and exit 1;
  FAKE_LLAMA_STATE counts them), slow:S (waits S s before each rerank reply).
FAKE_LLAMA_RECORD, when set, gets one JSON line per start (argv, pid) and per request (path, body).
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = sys.argv[1:]
MODES = [m for m in os.environ.get("FAKE_LLAMA", "").split(",") if m]
RECORD = os.environ.get("FAKE_LLAMA_RECORD")
STARTED = time.monotonic()
STATE = {"calls": 0}


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


def mode(name):
    for m in MODES:
        if m == name or m.startswith(name + ":"):
            return m.split(":", 1)[1] if ":" in m else True
    return None


def record(**fields):
    if RECORD:
        with open(RECORD, "a") as handle:
            handle.write(json.dumps(fields) + "\n")


def words(text):
    return {w.strip(".,;:?!").lower() for w in text.split() if w.strip(".,;:?!")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            return self.reply(404, {"error": "not found"})
        loading = float(mode("slow_load") or 0)
        if time.monotonic() - STARTED < loading:
            return self.reply(503, {"error": {"message": "Loading model"}})
        return self.reply(200, {"status": "ok"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        record(path=self.path, body=body, pid=os.getpid())
        if mode("reject_key") or self.headers.get("Authorization") != f"Bearer {arg('--api-key')}":
            return self.reply(401, {"error": {"message": "Invalid API Key"}})
        if self.path == "/tokenize":
            return self.reply(200, {"tokens": list(body["content"].encode())})
        if self.path == "/detokenize":
            return self.reply(200, {"content": bytes(body["tokens"]).decode("utf-8", "ignore")})
        probe = STATE["calls"] == 0
        STATE["calls"] += 1
        if not probe:
            if mode("crash"):
                os._exit(3)
            if mode("hang"):
                time.sleep(3600)
            time.sleep(float(mode("slow") or 0))
        if self.path == "/v1/rerank" and "--rerank" in ARGS:
            query = words(body["query"])
            results = [{"index": i, "relevance_score": 7 * len(query & words(d)) / max(1, len(query)) - 3}
                       for i, d in enumerate(body["documents"])]
            if not probe:
                if mode("wrong_count"):
                    results = results[:-1]
                if mode("duplicate_index") and len(results) > 1:
                    results[1]["index"] = 0
                if mode("nan"):
                    results[0]["relevance_score"] = float("nan")
            results.sort(key=lambda r: -r["relevance_score"])
            return self.reply(200, {"model": "fake", "results": results, "usage": {"prompt_tokens": 1}})
        return self.reply(404, {"error": "not found"})


def main():
    port = int(arg("--port"))
    record(argv=ARGS, pid=os.getpid())
    failures = int(mode("bind_fail") or 0)
    state = os.environ.get("FAKE_LLAMA_STATE")
    if failures and state:
        done = int(open(state).read() or 0) if os.path.exists(state) else 0
        if done < failures:
            open(state, "w").write(str(done + 1))
            print(f"couldn't bind HTTP server socket, hostname: 127.0.0.1, port: {port}", flush=True)
            sys.exit(1)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"couldn't bind HTTP server socket, hostname: 127.0.0.1, port: {port}", flush=True)
        sys.exit(1)
    print(f"main: server is listening on http://127.0.0.1:{port}", flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while True:
        time.sleep(3600)


main()
