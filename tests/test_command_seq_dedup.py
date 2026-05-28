"""Regression tests for CommandMessage.seq + per-connection dedup (B-21)."""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.core.models import CommandMessage, CommandType


def test_command_message_has_optional_seq_field():
    fields = CommandMessage.model_fields
    assert "seq" in fields
    # Backwards compatible: optional, default None.
    cmd = CommandMessage(timestamp=0.0, type=CommandType.DISARM)
    assert cmd.seq is None
    cmd2 = CommandMessage(timestamp=0.0, type=CommandType.DISARM, seq=7)
    assert cmd2.seq == 7


class _FakeWS:
    """Stand-in for the FastAPI WebSocket with the per-connection state attrs."""
    def __init__(self):
        self._last_ping_ts = 0.0
        self._last_seq = -1
        self.sent = []

    async def send_text(self, msg):
        self.sent.append(msg)


def test_dedup_drops_duplicate_seq(monkeypatch):
    """Same seq twice on one connection: second is dropped, both get ACK."""
    from src.comms import web_server as ws

    # Stub the cmd_pub so process_incoming_command doesn't need ZMQ.
    published = []
    class _FakePub:
        def send_string(self, m): published.append(m)
    monkeypatch.setattr(ws, "cmd_pub", _FakePub())

    fake_ws = _FakeWS()
    payload = json.dumps({
        "type": "DISARM",
        "timestamp": 0.0,
        "payload": {},
        "seq": 1,
    })

    asyncio.run(ws.process_incoming_command(payload, fake_ws))
    asyncio.run(ws.process_incoming_command(payload, fake_ws))   # replay

    # First accepted → publish + ack(duplicate=False).
    # Second dropped → no publish + ack(duplicate=True).
    assert len(published) == 1, f"expected 1 publish, got {len(published)}"
    assert fake_ws._last_seq == 1
    acks = [json.loads(m) for m in fake_ws.sent if json.loads(m)["topic"] == "comms/ack"]
    assert len(acks) == 2
    assert acks[0]["data"]["duplicate"] is False
    assert acks[1]["data"]["duplicate"] is True


def test_ping_does_not_publish_command(monkeypatch):
    """PING frames update liveness timestamp; do NOT enter the command path."""
    from src.comms import web_server as ws

    published = []
    class _FakePub:
        def send_string(self, m): published.append(m)
    monkeypatch.setattr(ws, "cmd_pub", _FakePub())

    fake_ws = _FakeWS()
    fake_ws._last_ping_ts = 0.0
    payload = json.dumps({"type": "PING", "seq": 1, "ts": 12345.0})
    asyncio.run(ws.process_incoming_command(payload, fake_ws))

    assert published == []
    assert fake_ws._last_ping_ts > 0.0   # bumped to monotonic now
    # PONG echoed back so client can measure RTT
    pongs = [json.loads(m) for m in fake_ws.sent if json.loads(m)["topic"] == "comms/pong"]
    assert len(pongs) == 1
    assert pongs[0]["data"]["seq"] == 1
