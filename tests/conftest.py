import os
import uuid

import pytest

os.environ.setdefault("SERVICE_KEY", "test-key")
os.environ.setdefault("NOTIFY_URL", "http://notify.invalid")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

KEY = os.environ["SERVICE_KEY"]


@pytest.fixture
def sent():
    """Notifications the service would post, in order."""
    return []


@pytest.fixture
def client(sent):
    main.state = main.State()
    main.state.notifier.send = sent_sender(sent)
    with TestClient(main.app) as c:
        yield c


def sent_sender(out):
    async def fake_send(n):
        out.append(n)
        return 200
    return fake_send


def call(c, op, body=None, key=KEY):
    headers = {"X-Service-Key": key} if key else {}
    body = {"idempotency_key": f"k-{uuid.uuid4()}", **(body or {})}
    return c.post(f"/v1/{op}", json=body, headers=headers)


def pay(c, token="test_ok", capture=False, amount="100.00", **extra):
    body = {"payment": str(uuid.uuid4()), "amount": amount, "currency": "RUB", "capture": capture,
            "payment_method": token, "metadata": {"notify_delay_ms": 0}, **extra}
    return call(c, "pay", body)


def roles(sent, n, timeout=3.0):
    """Roles of the notifications once n of them have been sent (they go out from a background task)."""
    import time
    t0 = time.monotonic()
    while len(sent) < n and time.monotonic() - t0 < timeout:
        time.sleep(0.02)
    time.sleep(0.05)
    return [x.role.value for x in sent]
