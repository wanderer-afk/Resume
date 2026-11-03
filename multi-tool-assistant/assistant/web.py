"""Small web UI: one chat page and a JSON endpoint. Standard library only.

  GET  /              chat page
  POST /api/chat      {"message": "..."} -> {"reply": "...", "trace": [...]}
  GET  /api/health    {"ok": true}
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .agent import Agent

MAX_MESSAGE_CHARS = 1000

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-tool assistant</title>
<style>
  :root { --bg:#f7f7f5; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --accent:#2f5d8a; --border:#e2e2dd; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161615; --fg:#ecebe6; --muted:#9a9a92; --card:#1f1f1d; --accent:#7fa8d6; --border:#333330; }
  }
  body { margin:0; font:16px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--fg); }
  main { max-width:720px; margin:0 auto; padding:16px; display:flex; flex-direction:column; min-height:100vh; box-sizing:border-box; }
  h1 { font-size:1.25rem; margin:8px 0 12px; }
  #log { flex:1; display:flex; flex-direction:column; gap:10px; overflow-y:auto; }
  .msg { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:10px 12px; white-space:pre-wrap; }
  .you { align-self:flex-end; border-color:var(--accent); }
  .trace { font:12px/1.4 ui-monospace, monospace; color:var(--muted); white-space:pre-wrap; }
  form { display:flex; gap:8px; margin-top:12px; position:sticky; bottom:0; background:var(--bg); padding:8px 0; }
  input { flex:1; font:inherit; padding:10px; border-radius:8px; border:1px solid var(--border); background:var(--card); color:var(--fg); min-width:0; }
  button { font:inherit; padding:10px 16px; border-radius:8px; border:0; background:var(--accent); color:#fff; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
</style></head>
<body><main>
  <h1>Multi-tool assistant</h1>
  <div id="log"><div class="msg">Try: "trip to Tokyo for 4 days", "weather in Kyoto", "facts about Japan", "add task pack passport".</div></div>
  <form id="form">
    <input id="input" name="message" placeholder="Ask something" maxlength="1000" autocomplete="off" required>
    <button id="send" type="submit">Send</button>
  </form>
</main>
<script>
const log = document.getElementById('log');
const form = document.getElementById('form');
const input = document.getElementById('input');
const send = document.getElementById('send');

function add(text, cls, extra) {
  const div = document.createElement('div');
  div.className = 'msg ' + (cls || '');
  div.textContent = text;
  if (extra) {
    const t = document.createElement('div');
    t.className = 'trace';
    t.textContent = extra;
    div.appendChild(t);
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  add(message, 'you');
  input.value = '';
  send.disabled = true;
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    add(data.reply, '', data.trace && data.trace.length ? data.trace.join('\\n') : '');
  } catch (err) {
    add('Something went wrong: ' + err.message);
  } finally {
    send.disabled = false;
    input.focus();
  }
});
</script>
</body></html>
"""


def handle_chat(agent: Agent, lock: threading.Lock, payload: Any) -> tuple[int, dict[str, Any]]:
    """Pure request logic, so it can be tested without a server."""
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
        return 400, {"error": "expected JSON body with a 'message' string"}
    message = payload["message"].strip()
    if not message:
        return 400, {"error": "message is empty"}
    if len(message) > MAX_MESSAGE_CHARS:
        return 400, {"error": f"message is longer than {MAX_MESSAGE_CHARS} characters"}
    with lock:  # the agent and profile are shared, so run one request at a time
        result = agent.run(message)
    return 200, {"reply": result.reply, "trace": result.trace}


def make_handler(agent: Agent) -> type[BaseHTTPRequestHandler]:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict[str, Any]) -> None:
            self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            if self.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/health":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/chat":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 10_000:
                    self._json(413, {"error": "request too large"})
                    return
                payload = json.loads(self.rfile.read(length) or b"null")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid JSON"})
                return
            status, body = handle_chat(agent, lock, payload)
            self._json(status, body)

        def log_message(self, fmt, *args) -> None:  # keep test and CLI output quiet
            pass

    return Handler


def serve(agent: Agent, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(agent))
    return server
