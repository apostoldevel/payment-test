"""test_drop against a real server: the client sees a closed connection, not a status."""
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from app import main
from tests.conftest import KEY


@pytest.fixture
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    t0 = time.monotonic()
    while not srv.started:
        assert time.monotonic() - t0 < 10, "server did not start"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(5)


def test_drop_is_a_closed_connection(server):
    body = {"idempotency_key": f"k-{uuid.uuid4()}", "payment": "p", "amount": "5", "payment_method": "test_drop",
            "metadata": {"notify_delay_ms": 60000}}
    h = {"X-Service-Key": KEY}
    with httpx.Client(timeout=5) as c:
        t0 = time.monotonic()
        with pytest.raises(httpx.TransportError):
            c.post(f"{server}/v1/pay", json=body, headers=h)
        assert time.monotonic() - t0 < 4
        r = c.post(f"{server}/v1/pay", json=body, headers=h)
    assert r.status_code == 200 and r.json()["outcome"] == "success"
    with httpx.Client(timeout=5) as c:
        s = c.post(f"{server}/v1/status", json={"idempotency_key": "s", "provider_id": r.json()["provider_id"]}, headers=h)
    assert s.json()["role"] == "hold", "the dropped operation did happen"
