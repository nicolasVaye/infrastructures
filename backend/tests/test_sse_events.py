"""SSE machinery invariants: sequence, ring buffer, replay, gap resync.

Runs on the SQLite in-process path (notify_event fans out directly), which
exercises the same _fanout/ring/replay code the Postgres LISTEN bridge uses.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import app.events as events


@pytest.fixture(autouse=True)
def _clean_state():
    events._subscribers.clear()
    events._ring.clear()
    events._seq = 0
    events._fanouts = 0
    yield
    events._subscribers.clear()


def test_fanout_assigns_monotonic_seq_and_buffers():
    for n in range(5):
        events._fanout(json.dumps({"type": "ping", "n": n}))
    assert [s for s, _ in events._ring] == [1, 2, 3, 4, 5]
    assert events.stats()["seq"] == 5


def test_explicit_seq_from_global_sequence_wins():
    # Postgres path: the replica embeds the global seq in the payload.
    events._fanout(json.dumps({"type": "ping", "_seq": 42}), )
    assert events._ring[-1][0] == 42


def test_ring_evicts_oldest_beyond_window():
    for n in range(events._REPLAY_WINDOW + 10):
        events._fanout(json.dumps({"type": "ping", "n": n}))
    seqs = [s for s, _ in events._ring]
    assert len(seqs) == events._REPLAY_WINDOW
    assert seqs == list(range(11, 11 + events._REPLAY_WINDOW))


async def test_stream_replays_missed_events_then_keeps_live():
    # Events 1..3 emitted BEFORE the subscriber connects (last_id=1):
    # the stream must replay 2..3, then deliver 4 live.
    for n in range(1, 4):
        events._fanout(json.dumps({"type": "ping", "n": n}))

    stream = events._event_stream(last_id=1)
    frames = []

    async def consume(count: int) -> None:
        for _ in range(count):
            frames.append(await stream.__anext__())

    task = asyncio.create_task(consume(4))
    await asyncio.sleep(0.05)
    events._fanout(json.dumps({"type": "ping", "n": 4}))
    await asyncio.wait_for(task, timeout=2.0)

    ids = [int(f.split("id: ")[1].split("\n")[0]) for f in frames[1:]]
    assert ids == [2, 3, 4]
    payload = json.loads(frames[3].split("data: ")[1].split("\n")[0])
    assert payload["n"] == 4


async def test_stream_resyncs_when_replay_window_exceeded():
    # Client at seq 0 but the ring only starts at (_REPLAY_WINDOW + 11):
    # everything before that is unrecoverable → the first data frame MUST
    # be a _resync marker.
    for n in range(1, events._REPLAY_WINDOW + 11):
        events._fanout(json.dumps({"type": "ping", "n": n}))
    assert events._ring[0][0] == 11  # window evicted events 1..10
    stream = events._event_stream(last_id=0)
    first = await stream.__anext__()   # retry/connected frame
    second = await stream.__anext__()  # first data frame
    assert second.startswith("id: 0\n")
    assert json.loads(second.split("data: ")[1].split("\n")[0])["type"] == "_resync"
    # The replayable tail is still delivered after the marker.
    third = await stream.__anext__()
    assert third.startswith(f"id: 11\n")
