from __future__ import annotations

import os
import ssl
import subprocess
import urllib.error
import urllib.request

CURL_BINARY = "curl"


class TransportError(RuntimeError):
    """Raised when a request cannot be completed."""


class HttpError(TransportError):
    """Raised when the server responds with a non-success status."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def get_bytes(url: str, headers: dict[str, str], timeout: float) -> bytes:
    """Fetch a URL, falling back to curl when the local trust store is unusable.

    python.org framework builds on macOS ship without a CA bundle unless the user
    runs Install Certificates.command, so urllib fails verification on an
    otherwise healthy machine. curl links the system trust store and succeeds.
    Verification is never disabled.
    """
    try:
        return _get_via_urllib(url, headers, timeout)
    except ssl.SSLCertVerificationError:
        return _get_via_curl(url, headers, timeout)
    except urllib.error.URLError as error:
        if isinstance(error.reason, ssl.SSLCertVerificationError):
            return _get_via_curl(url, headers, timeout)
        raise TransportError(f"network error: {error.reason}") from error


def _get_via_urllib(url: str, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_context()
        ) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise HttpError(error.code) from error


def _ssl_context() -> ssl.SSLContext:
    """Default context, pointed at certifi's bundle when one is installed."""
    context = ssl.create_default_context()
    if context.cert_store_stats().get("x509_ca", 0):
        return context
    if os.environ.get("SSL_CERT_FILE"):
        return context
    try:
        import certifi
    except ImportError:
        return context
    return ssl.create_default_context(cafile=certifi.where())


def _get_via_curl(url: str, headers: dict[str, str], timeout: float) -> bytes:
    config = _curl_config(url, headers, timeout)
    try:
        result = subprocess.run(
            [CURL_BINARY, "--config", "-"],
            input=config,
            capture_output=True,
            timeout=timeout + 5.0,
        )
    except FileNotFoundError as error:
        raise TransportError(
            "certificate verification failed and curl is unavailable"
        ) from error
    except subprocess.SubprocessError as error:
        raise TransportError(f"curl failed: {error}") from error

    body, status = _split_status(result.stdout)
    if status is None:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise TransportError(f"curl failed: {detail or 'no status returned'}")
    if status >= 400:
        raise HttpError(status)
    return body


def _curl_config(url: str, headers: dict[str, str], timeout: float) -> bytes:
    lines = [
        f'url = "{_escape(url)}"',
        "silent",
        "show-error",
        f"max-time = {timeout:.0f}",
        'write-out = "\\n%{http_code}"',
    ]
    lines.extend(f'header = "{_escape(f"{name}: {value}")}"' for name, value in headers.items())
    return ("\n".join(lines) + "\n").encode("utf-8")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _split_status(stdout: bytes) -> tuple[bytes, int | None]:
    """Separate the response body from the trailing status code curl appends."""
    separator = stdout.rfind(b"\n")
    if separator == -1:
        return b"", None
    body, tail = stdout[:separator], stdout[separator + 1 :]
    try:
        return body, int(tail.decode("ascii").strip())
    except ValueError:
        return b"", None
