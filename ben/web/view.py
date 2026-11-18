"""HTML visualization (static snapshot or live server)."""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
from pathlib import Path

from ben.core import paths
from ben.core.errors import FGError
from ben.core.graph import build_graph_view
from ben.core.store import Store
from ben.web.status import build_status_view


_VIEW_TEMPLATE = None  # cached


def _view_template_path() -> Path:
    return Path(__file__).resolve().parent / "template.html"


def _load_view_template() -> str:
    global _VIEW_TEMPLATE
    if _VIEW_TEMPLATE is None:
        _VIEW_TEMPLATE = _view_template_path().read_text(encoding="utf-8")
    return _VIEW_TEMPLATE


def _render_static_html(store: Store) -> str:
    """Inline the current graph + status into the HTML template as a snapshot."""
    tpl = _load_view_template()
    with store.locked():
        g = build_graph_view(store)
    s = build_status_view(store)
    # The JSON is embedded inside a <script>.  JSON escaping alone does not
    # prevent a fact containing `</script>` from terminating that script before
    # the browser parses it.  Escape HTML-significant characters while keeping
    # Unicode readable in the generated report.
    payload = (
        json.dumps(g, ensure_ascii=False, indent=2)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    status_payload = (
        json.dumps(s, ensure_ascii=False, indent=2)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    # replace the INLINE placeholders: `null /*__END__*/`  ->  <json> /*__END__*/
    tpl = tpl.replace(
        "/*__GRAPH_JSON__*/ null /*__END__*/",
        f"/*__GRAPH_JSON__*/ {payload} /*__END__*/",
    )
    tpl = tpl.replace(
        "/*__STATUS_JSON__*/ null /*__STATUS_END__*/",
        f"/*__STATUS_JSON__*/ {status_payload} /*__STATUS_END__*/",
    )
    return tpl


def cmd_view(args) -> int:
    store = Store(Path(args.store))
    store.require()

    if args.serve:
        return _view_serve(store, args)
    if args.print:
        sys.stdout.write(_render_static_html(store))
        return 0
    # default: write a snapshot into the runtime root (never beside the source
    # tree) and tell the user where it is
    out = Path(args.out) if args.out else paths.snapshot_file(store.root.parent)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_static_html(store), encoding="utf-8")
    # try to open it in the default browser (best-effort, non-fatal)
    opened = _try_open(out)
    print(f"wrote {out}")
    if opened:
        print(f"(opened in browser)")
    else:
        print(f"open it: file://{out.resolve()}")
    return 0


def _try_open(path: Path) -> bool:
    import shutil
    import subprocess
    opener = (
        shutil.which("xdg-open")
        or shutil.which("open")
        or shutil.which("wslview")
    )
    if not opener:
        return False
    try:
        subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _view_serve(store: Store, args) -> int:
    """Serve a live HTML view + a JSON poll endpoint via stdlib http.server."""
    import http.server
    import socketserver
    import threading

    host = args.host
    port = args.port
    # unguessable token so a random website can't fetch the graph even if it
    # knows the default path. Kept off the URL the browser
    # opens, baked into the served HTML instead.
    import secrets
    token = secrets.token_hex(12)
    poll_path = f"/__ben_graph__/{token}.json"
    status_path = f"/__ben_status__/{token}.json"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        # No CORS header — same-origin only. The bundled page is served
        # from the same host:port, so it doesn't need cross-origin reads.
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence default logging
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == poll_path:
                try:
                    with store.locked():
                        g = build_graph_view(store)
                except Exception as exc:
                    _send_json(self, {"error": str(exc)}, 500)
                    return
                _send_json(self, g)
                return
            if path == status_path:
                try:
                    s = build_status_view(store)
                except Exception as exc:
                    _send_json(self, {"error": str(exc)}, 500)
                    return
                _send_json(self, s)
                return
            if path == "/" or path == "/index.html":
                tpl = _load_view_template()
                tpl = tpl.replace('"__POLL_URL__"', f'"{poll_path}"')
                tpl = tpl.replace('"__STATUS_POLL_URL__"', f'"{status_path}"')
                body = tpl.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

    url = f"http://{host}:{port}/"
    print(f"[view] serving fact-graph  →  {url}")
    print(f"[view] polling JSON at     →  http://{host}:{port}{poll_path}")
    print(f"[view] status  JSON at     →  http://{host}:{port}{status_path}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("[view] WARNING: bound to a non-loopback host — the graph is "
              "readable by anyone who reaches this port.")
    print("[view] the page auto-refreshes every 2s. Ctrl-C to stop.")

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    # open the browser a moment after the server is up
    threading.Timer(0.4, _try_open_url, args=(url,)).start()

    try:
        with Server((host, port), Handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[view] stopped.")
    except OSError as exc:
        raise FGError(f"could not bind {host}:{port}: {exc}")
    return 0


def _try_open_url(url: str) -> None:
    import shutil
    import subprocess
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        try:
            subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
