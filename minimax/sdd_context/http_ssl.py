"""HTTPS helper that tolerates broken SSL_CERT_FILE settings on Windows.

Some conda installations export ``SSL_CERT_FILE`` to a path that no longer
exists, which makes ``ssl.create_default_context()`` fail before any request is
sent.  We always prefer certifi's CA bundle and drop invalid env overrides.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path


def build_ssl_context() -> ssl.SSLContext:
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        value = os.environ.get(name)
        if value and not Path(value).exists():
            os.environ.pop(name, None)
    try:
        import certifi  # type: ignore[import-not-found]

        cafile = certifi.where()
        if cafile and Path(cafile).is_file():
            return ssl.create_default_context(cafile=cafile)
    except Exception:
        pass
    return ssl.create_default_context()
