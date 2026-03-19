"""Tests for _cached_listdir in clop."""

import importlib.machinery
import importlib.util
import os
import tempfile
import time


def _load_clop():
    """Import clop as a module despite having no .py extension."""
    clop_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clop")
    loader = importlib.machinery.SourceFileLoader("clop", clop_path)
    spec = importlib.util.spec_from_file_location("clop", clop_path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    # clop uses curses and argparse at module level; we only need the cache function
    # so we patch just enough to allow import
    import types
    import sys
    # Provide a stub curses if not available (e.g., CI without a terminal)
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
_cached_listdir = clop._cached_listdir
_dir_listing_cache = clop._dir_listing_cache


class TestCachedListdir:
    """Tests for the _cached_listdir helper."""

    def setup_method(self):
        _dir_listing_cache.clear()

    def test_returns_listing(self, tmp_path):
        """Happy path: returns correct directory entries."""
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.jsonl").touch()
        result = _cached_listdir(str(tmp_path))
        assert sorted(result) == ["a.txt", "b.jsonl"]

    def test_cache_hit_returns_same_list(self, tmp_path):
        """Second call with unchanged dir returns cached list (same object)."""
        (tmp_path / "file").touch()
        first = _cached_listdir(str(tmp_path))
        second = _cached_listdir(str(tmp_path))
        assert first is second  # exact same list object = cache hit

    def test_cache_invalidated_on_new_file(self, tmp_path):
        """Adding a file changes dir mtime, so cache should refresh."""
        (tmp_path / "old.txt").touch()
        first = _cached_listdir(str(tmp_path))
        assert first == ["old.txt"]

        # Ensure mtime changes (some filesystems have 1s resolution)
        time.sleep(0.05)
        (tmp_path / "new.txt").touch()
        # Force mtime bump on directory
        os.utime(str(tmp_path), None)

        second = _cached_listdir(str(tmp_path))
        assert sorted(second) == ["new.txt", "old.txt"]
        assert first is not second  # different object = cache miss

    def test_nonexistent_directory(self):
        """Returns empty list for a directory that doesn't exist."""
        result = _cached_listdir("/nonexistent/path/unlikely")
        assert result == []

    def test_empty_directory(self, tmp_path):
        """Returns empty list for an empty directory."""
        result = _cached_listdir(str(tmp_path))
        assert result == []
