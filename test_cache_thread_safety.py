"""Tests for thread-safe cache access in clop.

Covers _proc_cache_lock, _subagent_cache_lock, and _dir_listing_cache_lock
added to prevent RuntimeError crashes in --serve mode.
"""

import importlib.machinery
import importlib.util
import os
import sys
import threading
import types


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


class TestCacheLockObjects:
    """Verify that each cache has an associated threading.Lock."""

    def test_proc_cache_lock_exists(self):
        assert hasattr(clop, "_proc_cache_lock")

    def test_proc_cache_lock_is_lock(self):
        assert isinstance(clop._proc_cache_lock, type(threading.Lock()))

    def test_subagent_cache_lock_exists(self):
        assert hasattr(clop, "_subagent_cache_lock")

    def test_subagent_cache_lock_is_lock(self):
        assert isinstance(clop._subagent_cache_lock, type(threading.Lock()))

    def test_dir_listing_cache_lock_exists(self):
        assert hasattr(clop, "_dir_listing_cache_lock")

    def test_dir_listing_cache_lock_is_lock(self):
        assert isinstance(clop._dir_listing_cache_lock, type(threading.Lock()))


class TestDirListingCacheThreadSafety:
    """_cached_listdir must not crash under concurrent access."""

    def setup_method(self):
        clop._dir_listing_cache.clear()

    def test_concurrent_reads_no_crash(self, tmp_path):
        """Many threads reading the same dir simultaneously must not raise."""
        for i in range(5):
            (tmp_path / f"file{i}.txt").touch()

        errors = []

        def worker():
            try:
                clop._cached_listdir(str(tmp_path))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent reads raised: {errors}"

    def test_concurrent_reads_and_writes_no_crash(self, tmp_path):
        """Interleaved cache reads and direct cache writes must not raise."""
        (tmp_path / "seed.txt").touch()
        errors = []

        def reader():
            try:
                for _ in range(50):
                    clop._cached_listdir(str(tmp_path))
            except Exception as exc:
                errors.append(exc)

        def writer():
            try:
                for i in range(50):
                    with clop._dir_listing_cache_lock:
                        clop._dir_listing_cache[f"/fake/path/{i}"] = (i, [f"f{i}"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        threads += [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent read/write raised: {errors}"


class TestSubagentCacheThreadSafety:
    """_subagent_cache reads and pruning must not crash under concurrency."""

    def setup_method(self):
        clop._subagent_cache.clear()

    def test_concurrent_reads_and_deletes_no_crash(self):
        """Simultaneous reads and deletions on _subagent_cache must not raise."""
        # Pre-populate with many entries
        for i in range(100):
            clop._subagent_cache[(f"/dir/{i}", f"agent-{i}")] = (float(i), {})

        errors = []

        def reader():
            try:
                for _ in range(100):
                    with clop._subagent_cache_lock:
                        _ = clop._subagent_cache.get((f"/dir/0", "agent-0"))
            except Exception as exc:
                errors.append(exc)

        def pruner():
            try:
                for i in range(0, 100, 2):
                    with clop._subagent_cache_lock:
                        clop._subagent_cache.pop((f"/dir/{i}", f"agent-{i}"), None)
            except Exception as exc:
                errors.append(exc)

        def inserter():
            try:
                for i in range(100, 200):
                    with clop._subagent_cache_lock:
                        clop._subagent_cache[(f"/dir/{i}", f"agent-{i}")] = (float(i), {})
            except Exception as exc:
                errors.append(exc)

        threads = (
            [threading.Thread(target=reader) for _ in range(5)]
            + [threading.Thread(target=pruner) for _ in range(5)]
            + [threading.Thread(target=inserter) for _ in range(5)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent subagent cache ops raised: {errors}"


class TestProcCacheThreadSafety:
    """_proc_cache reads, inserts, and deletions must not crash under concurrency."""

    def setup_method(self):
        clop._proc_cache.clear()

    def test_concurrent_inserts_and_deletes_no_crash(self):
        """Simultaneous inserts and deletes on _proc_cache must not raise."""
        errors = []

        # Use a sentinel object instead of a real psutil.Process
        sentinel = object()

        def inserter():
            try:
                for i in range(200):
                    with clop._proc_cache_lock:
                        clop._proc_cache[i] = sentinel
            except Exception as exc:
                errors.append(exc)

        def deleter():
            try:
                for i in range(200):
                    with clop._proc_cache_lock:
                        clop._proc_cache.pop(i, None)
            except Exception as exc:
                errors.append(exc)

        def stale_pruner():
            try:
                for _ in range(50):
                    with clop._proc_cache_lock:
                        seen = set(range(0, 200, 2))
                        for stale in set(clop._proc_cache) - seen:
                            del clop._proc_cache[stale]
            except Exception as exc:
                errors.append(exc)

        threads = (
            [threading.Thread(target=inserter) for _ in range(3)]
            + [threading.Thread(target=deleter) for _ in range(3)]
            + [threading.Thread(target=stale_pruner) for _ in range(3)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent proc cache ops raised: {errors}"
