"""Preview the site locally exactly as GitHub Pages serves it.

    python scripts/serve.py            # http://localhost:8000

Serves site/ at the root and data/ at /data/, the same layout the deploy workflow builds.
"""

import contextlib
import http.server
import sys
from functools import partial
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SITE, DATA = ROOT / "site", ROOT / "data"


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        clean = unquote(path.split("?", 1)[0].split("#", 1)[0])
        if clean.startswith("/data/"):
            target = (DATA / clean.removeprefix("/data/")).resolve()
            # refuse /data/../.. and friends: anything outside data/ is a 404
            if not target.is_relative_to(DATA.resolve()):
                return str(SITE / "__not_found__")
            return str(target)
        return super().translate_path(path)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(SITE)))
    print(f"Serving on http://localhost:{port}  (Ctrl+C to stop)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
