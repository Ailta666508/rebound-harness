from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest

from rebound import Step, Store
from rebound.verification import verify_snapshot


def test_cancelled_run_rejects_append_but_completed_run_accepts_next_plan(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([])
    store.set_status(run, "completed")
    store.append_step(run, Step(key="next", tool="write"))
    assert store.snapshot(run)["status"] == "pending"
    store.set_status(run, "cancelled")
    before = store.snapshot(run)
    with pytest.raises(ValueError, match="cancelled run"):
        store.append_step(run, Step(key="later", tool="write"))
    store.set_status(run, "completed")
    after = store.snapshot(run)
    assert after == before


def test_cancel_and_status_update_are_serialized(tmp_path):
    """Pause a completion after its read while another writer cancels the run."""
    selected, release, cancel_started, cancelled = Event(), Event(), Event(), Event()

    class PausedStore(Store):
        @contextmanager
        def connect(self):
            with super().connect() as db:
                class Connection:
                    def __getattr__(self, name):
                        return getattr(db, name)

                    def execute(self, sql, parameters=()):
                        cursor = db.execute(sql, parameters)
                        if sql == "SELECT status FROM runs WHERE id=?":
                            class Cursor:
                                def fetchone(self):
                                    row = cursor.fetchone()
                                    selected.set()
                                    assert release.wait(3), "test did not release paused writer"
                                    return row
                            return Cursor()
                        return cursor
                yield Connection()

    path = tmp_path / "state.sqlite"
    ordinary = Store(path)
    paused = PausedStore(path)
    run = ordinary.create_run([])

    def cancel():
        cancel_started.set()
        ordinary.set_status(run, "cancelled")
        cancelled.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        completion = executor.submit(paused.set_status, run, "completed")
        assert selected.wait(3)
        cancellation = executor.submit(cancel)
        assert cancel_started.wait(3)
        try:
            # With atomic status transitions, this writer cannot pass the first.
            assert not cancelled.wait(0.1)
        finally:
            release.set()
        completion.result(timeout=3)
        cancellation.result(timeout=3)
    assert ordinary.snapshot(run)["status"] == "cancelled"


def test_cancelled_run_cannot_persist_new_dispatch_intent(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([Step(key="one", tool="write")])
    operation = store.snapshot(run)["operations"][0]
    store.set_status(run, "cancelled")
    with pytest.raises(ValueError, match="cannot dispatch a cancelled run"):
        store.transition(operation["id"], "dispatched", increment=True)
    snap = store.snapshot(run)
    assert snap["operations"][0]["status"] == "planned"
    assert snap["operations"][0]["attempts"] == 0
    assert not any(event["kind"] == "operation.dispatched" for event in snap["events"])


def test_cancel_after_dispatch_still_allows_recording_actual_result(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([Step(key="one", tool="write")])
    operation = store.snapshot(run)["operations"][0]
    store.transition(operation["id"], "dispatched", increment=True)
    store.set_status(run, "cancelled")
    store.transition(operation["id"], "succeeded", result={"receipt": "actual-effect"})
    snap = store.snapshot(run)
    assert snap["status"] == "cancelled"
    assert snap["operations"][0]["result"] == {"receipt": "actual-effect"}
    assert verify_snapshot(snap)["valid"]


def test_manual_evidence_and_result_commit_atomically(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([Step(key="one", tool="write")])
    operation = store.snapshot(run)["operations"][0]
    store.transition(operation["id"], "dispatched", increment=True)
    store.transition(operation["id"], "unknown")
    before = store.snapshot(run)
    original = store._transition

    def interrupted(*args, **kwargs):
        raise RuntimeError("interrupted between human assertion and result")

    monkeypatch.setattr(store, "_transition", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        store.reconcile(run, operation["id"], {"receipt": "123"}, "Checked provider receipt")
    assert store.snapshot(run) == before

    monkeypatch.setattr(store, "_transition", original)
    store.reconcile(run, operation["id"], {"receipt": "123"}, "Checked provider receipt")
    snap = store.snapshot(run)
    assert snap["operations"][0]["status"] == "succeeded"
    assert [event["kind"] for event in snap["events"]][-2:] == [
        "recovery.manual", "operation.succeeded"
    ]
    assert verify_snapshot(snap)["valid"]
    with pytest.raises(ValueError, match="only an uncertain"):
        store.reconcile(run, operation["id"], {"receipt": "changed"}, "Another assertion")


def test_manual_resolution_is_bound_to_the_run(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    run = store.create_run([Step(key="one", tool="write")])
    other = store.create_run([])
    operation = store.snapshot(run)["operations"][0]
    store.transition(operation["id"], "dispatched", increment=True)
    with pytest.raises(ValueError, match="only an uncertain"):
        store.reconcile(other, operation["id"], {}, "Wrong run assertion")
    assert store.snapshot(run)["operations"][0]["status"] == "dispatched"
    assert not any(event["kind"] == "recovery.manual" for event in store.snapshot(other)["events"])
