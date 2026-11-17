"""Start the server: `python run.py`

If Office dev certificates are installed (`npx office-addin-dev-certs install`)
or SSL_CERTFILE / SSL_KEYFILE are set, the server runs on HTTPS, which Word
requires for add-ins. Otherwise it runs on plain HTTP (fine for the API and
for opening the task pane in a browser).

With RELOAD=1 the server restarts by itself whenever a file in backend/ or
.env changes. Changes are found by checking file times every second, so this
also works for edits made by tools that do not trigger file-system events.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_certificates():
    cert, key = os.getenv("SSL_CERTFILE"), os.getenv("SSL_KEYFILE")
    if cert and key:
        return cert, key
    folder = Path.home() / ".office-addin-dev-certs"
    cert, key = folder / "localhost.crt", folder / "localhost.key"
    if cert.is_file() and key.is_file():
        return str(cert), str(key)
    return None, None


def wait_for_port(host: str, port: int, seconds: float = 20) -> bool:
    """Wait until nothing is listening on the port (e.g. a server shutting down)."""
    deadline = time.time() + seconds
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
                return True
            except OSError:
                if time.time() >= deadline:
                    return False
        time.sleep(0.5)


def serve():
    """Run one server process in the foreground."""
    import uvicorn

    from backend.config import settings

    cert, key = find_certificates()
    scheme = "https" if cert else "http"
    base = f"{scheme}://localhost:{settings.server_port}"
    print(f"\n  API docs:   {base}/docs")
    print(f"  Task pane:  {base}/addin/taskpane.html")
    print(f"  Model:      {settings.openai_model}")
    if settings.chat_models[1:]:
        print(f"  Fallbacks:  {', '.join(settings.chat_models[1:])}")
    print(f"  Endpoint:   {settings.openai_base_url or 'https://api.openai.com/v1 (OpenAI default)'}")
    if not cert:
        print("  HTTPS:      off (Word needs it; see README, 'Word add-in')")
    print(flush=True)

    if not wait_for_port(settings.server_host, settings.server_port):
        print(
            f"Port {settings.server_port} is still in use by another program. "
            "Stop it, or set SERVER_PORT in .env to another port.",
            flush=True,
        )
        sys.exit(3)

    uvicorn.run(
        "backend.main:app",
        host=settings.server_host,
        port=settings.server_port,
        ssl_certfile=cert,
        ssl_keyfile=key,
        timeout_graceful_shutdown=5,
    )


def watched_files():
    files = list((ROOT / "backend").rglob("*.py"))
    files.append(ROOT / ".env")
    return files


def snapshot():
    state = {}
    for path in watched_files():
        try:
            state[str(path)] = path.stat().st_mtime_ns
        except FileNotFoundError:
            pass
    return state


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def supervise():
    """Run the server in a child process and restart it when files change."""
    print("  Reload:     on (restarts when backend code or .env changes)", flush=True)
    child_env = {**os.environ, "RELOAD": "0"}
    while True:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve())], env=child_env)
        state = snapshot()
        try:
            while True:
                time.sleep(1)
                if snapshot() != state:
                    print("\nChange detected, restarting the server...", flush=True)
                    stop(process)
                    break
                if process.poll() is not None:
                    print(
                        f"\nServer stopped (exit code {process.returncode}). "
                        "Waiting for a code or .env change to start it again "
                        "(Ctrl+C to quit)...",
                        flush=True,
                    )
                    while snapshot() == state:
                        time.sleep(1)
                    break
        except KeyboardInterrupt:
            stop(process)
            return


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if os.getenv("RELOAD", "").lower() in ("1", "true"):
        supervise()
    else:
        serve()
