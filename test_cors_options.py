"""Tests for CORS preflight OPTIONS handler on ClopAPIHandler."""

import importlib.machinery
import importlib.util
import io
import os
import sys
import types
from http.server import BaseHTTPRequestHandler
from unittest.mock import patch


def _load_clop():
    """Import clop as a module despite having no .py extension."""
    clop_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clop")
    loader = importlib.machinery.SourceFileLoader("clop", clop_path)
    spec = importlib.util.spec_from_file_location("clop", clop_path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    if "curses" not in sys.modules:
        curses_stub = types.ModuleType("curses")
        curses_stub.error = Exception
        curses_stub.color_pair = lambda x: 0
        curses_stub.A_BOLD = 0
        curses_stub.A_DIM = 0
        sys.modules["curses"] = curses_stub
    spec.loader.exec_module(mod)
    return mod


clop = _load_clop()


def _make_handler(method="OPTIONS", path="/api/run-skill"):
    """Construct a ClopAPIHandler with a fake socket, return (handler, response_bytes_io)."""
    output = io.BytesIO()

    class FakeSocket:
        def makefile(self, mode, **kwargs):
            request_line = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n\r\n"
            return io.BytesIO(request_line.encode())

        def getsockname(self):
            return ("127.0.0.1", 8080)

        def getpeername(self):
            return ("127.0.0.1", 12345)

        def sendall(self, data):
            output.write(data)

    # BaseHTTPRequestHandler processes the request in __init__
    with patch.object(clop.ClopAPIHandler, "handle_one_request", wraps=None) as _:
        pass

    handler = clop.ClopAPIHandler.__new__(clop.ClopAPIHandler)
    handler.raw_requestline = f"{method} {path} HTTP/1.1\r\n".encode()
    handler.rfile = io.BytesIO(b"")
    handler.wfile = output
    handler.connection = FakeSocket()
    handler.server = object()
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {}
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.command = method
    handler.path = path
    handler.request_version = "HTTP/1.1"

    return handler, output


def _call_options(path="/api/run-skill"):
    """Call do_OPTIONS and return the raw response bytes."""
    output = io.BytesIO()

    class FakeWfile:
        def write(self, data):
            output.write(data)

        def flush(self):
            pass

    handler = clop.ClopAPIHandler.__new__(clop.ClopAPIHandler)
    handler.wfile = FakeWfile()
    handler.request_version = "HTTP/1.1"
    handler.path = path
    handler.command = "OPTIONS"
    handler.close_connection = False

    sent_headers = {}
    status_code = []

    def fake_send_response(code, message=None):
        status_code.append(code)

    def fake_send_header(key, value):
        sent_headers[key] = value

    def fake_end_headers():
        pass

    handler.send_response = fake_send_response
    handler.send_header = fake_send_header
    handler.end_headers = fake_end_headers

    handler.do_OPTIONS()
    return status_code, sent_headers


class TestCorsOptionsHandler:
    """ClopAPIHandler.do_OPTIONS must respond correctly to CORS preflight requests."""

    def test_options_returns_200(self):
        """OPTIONS request must return HTTP 200."""
        status_code, _ = _call_options()
        assert status_code == [200], f"Expected [200], got {status_code}"

    def test_options_allows_origin_wildcard(self):
        """Preflight response must include Access-Control-Allow-Origin: *."""
        _, headers = _call_options()
        assert headers.get("Access-Control-Allow-Origin") == "*"

    def test_options_allows_post_method(self):
        """Preflight response must allow POST (needed for /api/run-skill)."""
        _, headers = _call_options()
        allowed = headers.get("Access-Control-Allow-Methods", "")
        assert "POST" in allowed, f"POST not in Allow-Methods: {allowed!r}"

    def test_options_allows_get_method(self):
        """Preflight response must allow GET (needed for /api/sessions etc.)."""
        _, headers = _call_options()
        allowed = headers.get("Access-Control-Allow-Methods", "")
        assert "GET" in allowed, f"GET not in Allow-Methods: {allowed!r}"

    def test_options_allows_content_type_header(self):
        """Preflight must permit Content-Type header (sent by JSON POST clients)."""
        _, headers = _call_options()
        allowed = headers.get("Access-Control-Allow-Headers", "")
        assert "Content-Type" in allowed, f"Content-Type not in Allow-Headers: {allowed!r}"

    def test_options_responds_to_any_api_path(self):
        """OPTIONS should return 200 regardless of which API path is targeted."""
        for path in ("/api/run-skill", "/api/sessions", "/api/run-suggestions"):
            status_code, _ = _call_options(path=path)
            assert status_code == [200], f"Expected 200 for OPTIONS {path}, got {status_code}"

    def test_options_has_zero_content_length(self):
        """Preflight response body is empty; Content-Length must be 0."""
        _, headers = _call_options()
        assert headers.get("Content-Length") == "0"
