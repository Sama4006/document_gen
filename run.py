"""Start the server: `python run.py`

If Office dev certificates are installed (`npx office-addin-dev-certs install`)
or SSL_CERTFILE / SSL_KEYFILE are set, the server runs on HTTPS, which Word
requires for add-ins. Otherwise it runs on plain HTTP (fine for the API and
for opening the task pane in a browser).
"""

import os
from pathlib import Path

import uvicorn

from backend.config import settings


def find_certificates():
    cert, key = os.getenv("SSL_CERTFILE"), os.getenv("SSL_KEYFILE")
    if cert and key:
        return cert, key
    folder = Path.home() / ".office-addin-dev-certs"
    cert, key = folder / "localhost.crt", folder / "localhost.key"
    if cert.is_file() and key.is_file():
        return str(cert), str(key)
    return None, None


if __name__ == "__main__":
    cert, key = find_certificates()
    scheme = "https" if cert else "http"
    base = f"{scheme}://localhost:{settings.server_port}"
    print(f"\n  API docs:   {base}/docs")
    print(f"  Task pane:  {base}/addin/taskpane.html")
    print(f"  Model:      {settings.openai_model}")
    if not cert:
        print("  HTTPS:      off (Word needs it; see README, 'Word add-in')")
    print()
    uvicorn.run(
        "backend.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=os.getenv("RELOAD", "").lower() in ("1", "true"),
        ssl_certfile=cert,
        ssl_keyfile=key,
    )
