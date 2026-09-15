#!/bin/zsh
# Start JobTailor dashboard (API + web) and open it in your browser.
cd "$HOME/jobtailor" || exit 1

# Start the API if it isn't already running
if ! curl -s -m 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  nohup "$HOME/jobtailor/.venv/bin/jobtailor" serve --port 8000 > "$HOME/jobtailor/output/server.log" 2>&1 &
fi

# Start the web dashboard if it isn't already running
if ! curl -s -m 2 -o /dev/null http://localhost:3000/ 2>/dev/null; then
  (cd "$HOME/jobtailor/dashboard" && nohup pnpm dev > "$HOME/jobtailor/output/dashboard.log" 2>&1 &)
fi

sleep 4
open "http://localhost:3000"