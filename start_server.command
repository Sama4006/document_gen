#!/bin/bash
# Double-click to (re)start the DocGen server. Output is also saved to server.log.
# Running it again is safe: it stops the previous server first.
cd "$(dirname "$0")" || exit 1
LOG=server.log
exec > >(tee "$LOG") 2>&1
echo "=== $(date) ==="

# Stop anything listening on port 8000 (an earlier copy of this server).
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  PIDS=$(lsof -ti tcp:8000 -sTCP:LISTEN)
  [ -z "$PIDS" ] && break
  for p in $PIDS; do echo "Stopping PID $p: $(ps -o command= -p "$p")"; done
  # Also stop the parent watcher of an earlier run, so it doesn't restart it.
  for p in $PIDS; do pp=$(ps -o ppid= -p "$p" | tr -d ' '); ps -o command= -p "$pp" 2>/dev/null | grep -q "run.py" && kill "$pp" 2>/dev/null; done
  if [ "$attempt" -le 6 ]; then kill $PIDS 2>/dev/null; else kill -9 $PIDS 2>/dev/null; fi
  sleep 1
done
lsof -ti tcp:8000 -sTCP:LISTEN >/dev/null && echo "WARNING: port 8000 is still busy" || echo "port 8000 free"
env | grep '^OPENAI_' | sed -E 's/(KEY=).*/\1<hidden>/'

[ -x venv/bin/python ] || python3 -m venv venv
source venv/bin/activate
python -c "import fastapi, uvicorn, chromadb, openai, docx, pypdf, pydantic_settings, multipart" 2>/dev/null \
  || pip install -r backend/requirements.txt 2>&1 | tail -5
echo "python: $(python --version 2>&1) at $(which python)"

export RELOAD=1  # restart automatically when backend code or .env changes
python -u run.py
echo "Server stopped. You can close this window."
