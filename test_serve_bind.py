"""Tests for serve_mode bind address — must bind to localhost only."""

import importlib.machinery
import importlib.util
import os
import sys
import types
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


def _run_serve_mode(port=9999):
    """Run serve_mode with all blocking calls patched; return list of (host, port) tuples bound."""
    bound_addresses = []

    class CapturingHTTPServer:
        def __init__(self, addr, handler):
            bound_addresses.append(addr)

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

    with (
        patch.object(clop, "find_claude_processes"),
        patch.object(clop.threading, "Thread"),
        patch.object(clop.time, "sleep"),
        patch.object(clop, "HTTPServer", CapturingHTTPServer),
    ):
        try:
            clop.serve_mode(port)
        except KeyboardInterrupt:
            pass

    return bound_addresses


class TestServeModeBind:
    """Verify that serve_mode binds to 127.0.0.1, not 0.0.0.0."""

    def test_binds_to_localhost(self):
        """serve_mode must create HTTPServer bound to 127.0.0.1."""
        bound = _run_serve_mode(9999)
        assert len(bound) == 1
        host, port = bound[0]
        assert host == "127.0.0.1", f"Expected 127.0.0.1, got {host!r}"
        assert port == 9999

    def test_does_not_bind_to_all_interfaces(self):
        """serve_mode must not use 0.0.0.0 (would expose API to the network)."""
        bound = _run_serve_mode(9999)
        host, _ = bound[0]
        assert host != "0.0.0.0", "Server must not bind to 0.0.0.0 — use 127.0.0.1 instead"
