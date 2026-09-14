"""DEIXIS local launcher: `python -m deixis serve`."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from deixis.api.app import create_app
from deixis.config import Settings, load_settings


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform != "win32":  # like uvicorn; lingering closed connections must not look like a running server
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def serve(settings: Settings, open_browser: bool, dev_hosts: tuple[str, ...]) -> int:
    url = f"http://{settings.host}:{settings.port}/"
    if settings.host not in ("127.0.0.1", "localhost"):
        print("DEIXIS binds to loopback only; set DEIXIS_HOST=127.0.0.1.", file=sys.stderr)
        return 2
    if not port_available(settings.host, settings.port):
        print(f"Port {settings.port} is in use. DEIXIS may already be running at {url} — "
              "open it, stop the other process, or set DEIXIS_PORT.", file=sys.stderr)
        return 2
    if not settings.web_dist.exists():
        print("UI build not found (apps/web/dist). The API will run; build the UI with `npm run build` in apps/web.")
    # Open event streams would otherwise hold graceful shutdown (and the port) until the browser disconnects.
    server = uvicorn.Server(uvicorn.Config(create_app(settings, extra_hosts=dev_hosts), host=settings.host,
                                           port=settings.port, log_level="info", timeout_graceful_shutdown=3))

    def open_when_ready() -> None:
        for _ in range(100):
            if server.started:
                print(f"DEIXIS is running at {url}")
                if open_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.1)

    threading.Thread(target=open_when_ready, daemon=True).start()
    server.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deixis")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("serve", help="Start the local API, worker and UI")
    run.add_argument("--port", type=int)
    run.add_argument("--no-browser", action="store_true")
    run.add_argument("--dev", action="store_true", help="Also accept requests proxied from the Vite dev server (port 5178)")
    args = parser.parse_args(argv)
    settings = load_settings()
    if args.port:
        settings = Settings(data_dir=settings.data_dir, host=settings.host, port=args.port)
    dev_hosts = ("127.0.0.1:5178", "localhost:5178") if args.dev else ()
    return serve(settings, not args.no_browser, dev_hosts)


if __name__ == "__main__":
    sys.exit(main())
