"""Minimal OpenAI-compatible chat.completions server for zero-token CI.

Scripted responses: first N calls return tool_calls, then a final JSON string.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class ScriptedHandler(BaseHTTPRequestHandler):
    script: list = []
    call_n = 0

    def log_message(self, fmt, *args):  # quiet
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _body = self.rfile.read(length)
        idx = ScriptedHandler.call_n
        ScriptedHandler.call_n += 1
        if idx < len(ScriptedHandler.script):
            payload = ScriptedHandler.script[idx]
        else:
            payload = {
                "id": "chatcmpl-end",
                "object": "chat.completion",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": '{"accepted":true,"data":{}}'},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def make_tool_turn(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments),
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def make_final(content: str) -> dict:
    return {
        "id": "chatcmpl-final",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


def start_server(script: list[dict], host: str = "127.0.0.1", port: int = 0):
    ScriptedHandler.script = list(script)
    ScriptedHandler.call_n = 0
    server = HTTPServer((host, port), ScriptedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]
