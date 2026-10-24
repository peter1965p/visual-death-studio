"""Minimaler lokaler Ersatz für die Claude-API (POST /v1/messages, Streaming per SSE) für Tests – ohne Netzwerk und ohne Schlüssel."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sse(blocks, stop_reason="end_turn", model="claude-test"):
    """blocks: [("text", "…")] oder [("tool_use", name, input_dict)] → SSE-Ereignisse im Format der Messages-API."""
    ev = [("message_start", {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "content": [], "model": model,
                                                                  "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}})]
    for i, b in enumerate(blocks):
        if b[0] == "text":
            ev += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b[1]}})]
        else:
            raw = json.dumps(b[2])
            ev += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": f"toolu_{i}", "name": b[1], "input": {}}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": raw[:len(raw) // 2]}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": raw[len(raw) // 2:]}})]
        ev.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    ev += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": 5}}),
           ("message_stop", {"type": "message_stop"})]
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in ev)


class FakeApi:
    """Antworten werden der Reihe nach aus `script` genommen: str (SSE-Text), oder (status, json_dict) für Fehler. Alle Anfragen landen in `requests`."""

    def __init__(self, script):
        self.script, self.requests, self.headers = list(script), [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                outer.requests.append(body); outer.headers.append(dict(self.headers))
                item = outer.script.pop(0) if outer.script else sse([("text", "(Skript leer)")])
                if isinstance(item, tuple):
                    data = json.dumps(item[1]).encode()
                    self.send_response(item[0]); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(data)))
                    self.end_headers(); self.wfile.write(data)
                    return
                if not body.get("stream"):                                   # nicht gestreamt: fertige Nachricht als JSON
                    msg = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-test", "stop_reason": "end_turn", "stop_sequence": None,
                           "usage": {"input_tokens": 10, "output_tokens": 5}, "content": [{"type": "text", "text": _first_text(item)}]}
                    data = json.dumps(msg).encode()
                    self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(data)))
                    self.end_headers(); self.wfile.write(data)
                    return
                data = item.encode()
                self.send_response(200); self.send_header("content-type", "text/event-stream"); self.send_header("content-length", str(len(data)))
                self.end_headers(); self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown(); self.server.server_close()


def _first_text(sse_text: str) -> str:
    for block in sse_text.split("\n\n"):
        if '"text_delta"' in block:
            return json.loads(block.split("data: ", 1)[1])["delta"]["text"]
    return ""
