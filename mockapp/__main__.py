"""Run the mock credit-union admin app:  python -m mockapp  (serves on :5050)."""
from __future__ import annotations

import os

from .server import MockServer

if __name__ == "__main__":
    port = int(os.environ.get("CUA_MOCKAPP_PORT", "5050"))
    srv = MockServer(port=port)
    srv._thread.start()
    print(f" * mock credit-union admin on {srv.base_url}  (Ctrl-C to stop)")
    try:
        srv._thread.join()
    except KeyboardInterrupt:
        srv.stop()
