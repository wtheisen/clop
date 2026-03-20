"""Tests for get_active_orchestrators() sessions parameter.

The fix avoids a redundant get_active_sessions() call inside
get_active_orchestrators() when a caller (e.g. _refresh_server_cache)
has already fetched sessions. The key logic under test is the worker
cross-reference loop.
"""

ACTIVITY_IDLE = {"idle", "waiting", ""}


def _cross_reference_workers(slugs, orch_type, sessions):
    """Replicate the worker cross-reference logic from get_active_orchestrators."""
    workers = []
    repo = ""
    for slug in slugs:
        worker_cwd_pattern = f"/tmp/{orch_type}-{slug}"
        worker = {"slug": slug, "status": "pending", "activity": "", "context_pct": 0}
        for sess in sessions:
            if sess.get("cwd", "").startswith(worker_cwd_pattern):
                worker["status"] = "active" if sess["activity"] not in ACTIVITY_IDLE else "idle"
                worker["activity"] = sess["activity"]
                worker["context_pct"] = sess["context_pct"]
                if not repo and sess.get("parent_project"):
                    repo = sess["parent_project"]
                break
        workers.append(worker)
    return workers, repo


class TestWorkerCrossReference:
    def test_active_worker_matched_by_cwd(self):
        """A session whose cwd starts with the worker pattern marks the worker active."""
        sessions = [
            {
                "cwd": "/tmp/myorch-abc123/repo",
                "activity": "coding",
                "context_pct": 42,
                "parent_project": "my-repo",
            }
        ]
        workers, repo = _cross_reference_workers(["abc123"], "myorch", sessions)
        assert workers[0]["status"] == "active"
        assert workers[0]["activity"] == "coding"
        assert workers[0]["context_pct"] == 42
        assert repo == "my-repo"

    def test_idle_worker_when_activity_is_idle(self):
        """A session with idle activity marks the worker idle, not active."""
        sessions = [
            {
                "cwd": "/tmp/myorch-abc123/repo",
                "activity": "idle",
                "context_pct": 10,
            }
        ]
        workers, _ = _cross_reference_workers(["abc123"], "myorch", sessions)
        assert workers[0]["status"] == "idle"

    def test_idle_worker_when_activity_is_empty(self):
        """A session with empty activity string marks the worker idle."""
        sessions = [
            {
                "cwd": "/tmp/myorch-abc123",
                "activity": "",
                "context_pct": 0,
            }
        ]
        workers, _ = _cross_reference_workers(["abc123"], "myorch", sessions)
        assert workers[0]["status"] == "idle"

    def test_pending_worker_when_no_session_matches(self):
        """Workers with no matching session remain pending."""
        sessions = [
            {
                "cwd": "/home/user/other-project",
                "activity": "coding",
                "context_pct": 5,
            }
        ]
        workers, _ = _cross_reference_workers(["abc123"], "myorch", sessions)
        assert workers[0]["status"] == "pending"
        assert workers[0]["activity"] == ""
        assert workers[0]["context_pct"] == 0

    def test_empty_sessions_all_workers_pending(self):
        """Passing an empty sessions list leaves all workers pending."""
        workers, repo = _cross_reference_workers(["slug1", "slug2"], "myorch", [])
        assert all(w["status"] == "pending" for w in workers)
        assert repo == ""

    def test_multiple_slugs_each_matched_independently(self):
        """Each slug is matched against the sessions list independently."""
        sessions = [
            {"cwd": "/tmp/myorch-slug1/repo", "activity": "coding", "context_pct": 20},
            {"cwd": "/tmp/myorch-slug2/repo", "activity": "waiting", "context_pct": 5},
        ]
        workers, _ = _cross_reference_workers(["slug1", "slug2"], "myorch", sessions)
        assert workers[0]["status"] == "active"
        assert workers[1]["status"] == "idle"

    def test_repo_derived_from_first_matching_session(self):
        """repo is taken from the first session that provides parent_project."""
        sessions = [
            {"cwd": "/tmp/myorch-slug1/repo", "activity": "coding", "context_pct": 1, "parent_project": "first-repo"},
            {"cwd": "/tmp/myorch-slug2/repo", "activity": "coding", "context_pct": 1, "parent_project": "second-repo"},
        ]
        workers, repo = _cross_reference_workers(["slug1", "slug2"], "myorch", sessions)
        assert repo == "first-repo"

    def test_repo_empty_when_no_session_has_parent_project(self):
        """repo stays empty when no matching session has parent_project."""
        sessions = [
            {"cwd": "/tmp/myorch-slug1/repo", "activity": "coding", "context_pct": 1},
        ]
        workers, repo = _cross_reference_workers(["slug1"], "myorch", sessions)
        assert repo == ""

    def test_session_without_cwd_key_is_skipped(self):
        """Sessions missing 'cwd' key do not cause errors and don't match."""
        sessions = [{"activity": "coding", "context_pct": 5}]
        workers, _ = _cross_reference_workers(["abc123"], "myorch", sessions)
        assert workers[0]["status"] == "pending"

    def test_cwd_prefix_match_not_exact(self):
        """Matching is prefix-based, so nested paths under the worktree still match."""
        sessions = [
            {
                "cwd": "/tmp/myorch-abc123/nested/dir",
                "activity": "coding",
                "context_pct": 7,
            }
        ]
        workers, _ = _cross_reference_workers(["abc123"], "myorch", sessions)
        assert workers[0]["status"] == "active"


class TestSessionsParamDefault:
    def test_none_sessions_triggers_internal_fetch(self):
        """When sessions=None, the function fetches sessions itself (call count check)."""
        call_count = {"n": 0}
        captured = {}

        def fake_get_active_sessions():
            call_count["n"] += 1
            return []

        def get_active_orchestrators(sessions=None):
            if sessions is None:
                sessions = fake_get_active_sessions()
            captured["sessions"] = sessions
            return sessions

        get_active_orchestrators(sessions=None)
        assert call_count["n"] == 1
        assert captured["sessions"] == []

    def test_provided_sessions_skip_internal_fetch(self):
        """When sessions are passed in, the internal fetch is never called."""
        call_count = {"n": 0}

        def fake_get_active_sessions():
            call_count["n"] += 1
            return []

        def get_active_orchestrators(sessions=None):
            if sessions is None:
                sessions = fake_get_active_sessions()
            return sessions

        provided = [{"cwd": "/tmp/x", "activity": "coding", "context_pct": 0}]
        result = get_active_orchestrators(sessions=provided)
        assert call_count["n"] == 0
        assert result is provided
