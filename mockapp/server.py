"""In-process server handle for the mock app -- used by the CLI's ``--serve-mock``
convenience and by the test suite so no external process is needed.
"""
from __future__ import annotations

import threading

from werkzeug.serving import make_server

from . import create_app


class MockServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 5050) -> None:
        self.host, self.port = host, port
        self._srv = make_server(host, port, create_app(), threaded=True)
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "MockServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def stop(self) -> None:
        self._srv.shutdown()
        self._thread.join(timeout=3)
