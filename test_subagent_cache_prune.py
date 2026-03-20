"""Tests for subagent cache pruning fix (KeyError on missing _subagent_dir)."""


def _prune_subagent_cache(subagent_cache, cached_sessions):
    """Replicate the pruning logic from clop's main() refresh block."""
    active_subagent_keys = set()
    for s in cached_sessions:
        for a in s.get("subagents", []):
            subdir = a.get("_subagent_dir")
            if subdir:
                active_subagent_keys.add((subdir, a["agent_id"]))
    for stale_key in set(subagent_cache) - active_subagent_keys:
        del subagent_cache[stale_key]


class TestSubagentCachePrune:
    def test_no_keyerror_for_agent_without_subagent_dir(self):
        """Agents missing _subagent_dir (no-JSONL branch) must not raise KeyError."""
        cache = {("/some/dir", "agent-1"): ("mtime", {})}
        sessions = [
            {
                "pid": 1,
                "subagents": [
                    # no _subagent_dir key — the bug case
                    {"agent_id": "agent-no-jsonl", "type": "subagent"},
                ]
            }
        ]
        # Must not raise
        _prune_subagent_cache(cache, sessions)

    def test_stale_entry_pruned_when_session_gone(self):
        """Cache entry for an agent no longer in any session is removed."""
        cache = {("/dir/a", "agent-1"): ("mtime", {})}
        _prune_subagent_cache(cache, [])
        assert cache == {}

    def test_active_entry_kept(self):
        """Cache entry for an active agent is retained."""
        cache = {("/dir/a", "agent-1"): ("mtime", {})}
        sessions = [
            {
                "pid": 1,
                "subagents": [
                    {"agent_id": "agent-1", "_subagent_dir": "/dir/a"},
                ]
            }
        ]
        _prune_subagent_cache(cache, sessions)
        assert ("/dir/a", "agent-1") in cache

    def test_mixed_agents_only_stale_pruned(self):
        """Mix of agents with and without _subagent_dir; stale entries removed, active kept."""
        cache = {
            ("/dir/a", "agent-1"): ("mtime", {}),
            ("/dir/b", "agent-2"): ("mtime", {}),
        }
        sessions = [
            {
                "pid": 1,
                "subagents": [
                    # agent-1 is active with _subagent_dir
                    {"agent_id": "agent-1", "_subagent_dir": "/dir/a"},
                    # agent-no-jsonl has no _subagent_dir (no-JSONL branch)
                    {"agent_id": "agent-no-jsonl"},
                ]
            }
        ]
        _prune_subagent_cache(cache, sessions)
        assert ("/dir/a", "agent-1") in cache
        assert ("/dir/b", "agent-2") not in cache

    def test_empty_cache_and_sessions(self):
        """No-op on empty inputs."""
        cache = {}
        _prune_subagent_cache(cache, [])
        assert cache == {}

    def test_session_with_no_subagents_key(self):
        """Sessions without a 'subagents' key are skipped safely."""
        cache = {("/dir/a", "agent-1"): ("mtime", {})}
        sessions = [{"pid": 1}]  # no 'subagents' key
        _prune_subagent_cache(cache, sessions)
        assert cache == {}  # stale entry pruned
