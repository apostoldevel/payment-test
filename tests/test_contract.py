import time
import uuid

import pytest

from tests.conftest import KEY, call, pay, roles

OPS = ("pay", "capture", "cancel", "refund", "status", "bind", "unbind")


def ok(r, outcome="success", role=None):
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["outcome"] == outcome, b
    if role is not None:
        assert b["role"] == role, b
    return b


class TestKey:
    @pytest.mark.parametrize("op", OPS)
    def test_missing_key_is_401(self, client, op):
        r = call(client, op, {"payment_method": "test_ok"}, key=None)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"

    def test_wrong_key_is_401_before_the_body_is_read(self, client):
        r = client.post("/v1/pay", content=b"not json", headers={"X-Service-Key": "wrong"})
        assert r.status_code == 401

    def test_a_refused_call_records_nothing(self, client):
        ik = f"k-{uuid.uuid4()}"
        body = {"idempotency_key": ik, "payment": "p", "amount": "1", "payment_method": "test_decline"}
        assert client.post("/v1/pay", json=body, headers={"X-Service-Key": "wrong"}).status_code == 401
        body["payment_method"] = "test_ok"
        ok(client.post("/v1/pay", json=body, headers={"X-Service-Key": KEY}))

    def test_open_routes_need_no_key(self, client):
        assert client.get("/health").status_code == 200
        assert client.get("/openapi.json").status_code == 200

    def test_renotify_needs_the_key(self, client):
        assert client.post("/test/renotify/x").status_code == 401


class TestScenarios:
    def test_ok_hold(self, client, sent):
        b = ok(pay(client), role="hold")
        assert b["provider_status"] == "authorized" and b["provider_id"].startswith("tp_")
        assert roles(sent, 1) == ["hold"]

    def test_ok_paid_at_once(self, client):
        ok(pay(client, capture=True), role="paid")

    def test_decline(self, client, sent):
        b = ok(pay(client, "test_decline"), outcome="declined", role="failed")
        assert b["error"]["code"] == "card_declined"
        assert roles(sent, 1) == ["failed"]

    def test_unknown_then_status_tells_the_truth(self, client, sent):
        b = ok(pay(client, "test_unknown"), outcome="unknown", role="pending")
        ok(call(client, "status", {"provider_id": b["provider_id"]}), role="hold")
        assert roles(sent, 1) == ["hold"]

    def test_unknown_with_capture_is_paid_underneath(self, client):
        b = ok(pay(client, "test_unknown", capture=True), outcome="unknown", role="pending")
        ok(call(client, "status", {"provider_id": b["provider_id"]}), role="paid")

    def test_drop_closes_without_an_answer_and_the_repeat_gets_it(self, client):
        body = {"idempotency_key": f"k-{uuid.uuid4()}", "payment": "p", "amount": "10", "payment_method": "test_drop",
                "metadata": {"notify_delay_ms": 0}}
        with pytest.raises(ConnectionAbortedError):
            client.post("/v1/pay", json=body, headers={"X-Service-Key": KEY})
        r1 = client.post("/v1/pay", json=body, headers={"X-Service-Key": KEY})
        r2 = client.post("/v1/pay", json=body, headers={"X-Service-Key": KEY})
        assert ok(r1, role="hold") == r2.json()

    def test_payment_method_is_a_string(self, client):
        r = pay(client, {"id": "test_ok"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"

    def test_unknown_token_is_declined(self, client):
        ok(pay(client, "test_nope"), outcome="declined")


class TestMoney:
    def test_capture_partial_and_full_refund(self, client, sent):
        pid = ok(pay(client))["provider_id"]
        ok(call(client, "capture", {"provider_id": pid, "amount": "100.00"}), role="paid")
        ok(call(client, "refund", {"provider_id": pid, "amount": "30.00"}), role="partial_refunded")
        b = ok(call(client, "refund", {"provider_id": pid, "amount": 70}), role="refunded")
        assert b["raw"]["refunded_amount"] == "100.00"
        assert roles(sent, 4) == ["hold", "paid", "partial_refunded", "refunded"]

    def test_capture_without_amount_takes_the_hold(self, client):
        pid = ok(pay(client, amount="42.50"))["provider_id"]
        assert ok(call(client, "capture", {"provider_id": pid}), role="paid")["raw"]["captured_amount"] == "42.50"

    def test_cancel_of_a_hold(self, client):
        pid = ok(pay(client))["provider_id"]
        ok(call(client, "cancel", {"provider_id": pid}), role="canceled")
        b = ok(call(client, "capture", {"provider_id": pid}), outcome="declined", role="canceled")
        assert b["error"]["code"] == "invalid_state"

    def test_refund_above_paid_is_declined_and_changes_nothing(self, client):
        pid = ok(pay(client, capture=True))["provider_id"]
        b = ok(call(client, "refund", {"provider_id": pid, "amount": "100.01"}), outcome="declined", role="paid")
        assert b["error"]["code"] == "amount_exceeds"
        ok(call(client, "refund", {"provider_id": pid, "amount": "100.00"}), role="refunded")

    @pytest.mark.parametrize("op", ("capture", "cancel", "refund", "status"))
    def test_unknown_payment_is_a_declined_200(self, client, op):
        b = ok(call(client, op, {"provider_id": "tp_none", "amount": "1"}), outcome="declined")
        assert b["role"] is None and b["error"]["code"] == "payment_not_found"

    @pytest.mark.parametrize("amount", ("0", "-1", "abc", True))
    def test_bad_amount_is_422(self, client, amount):
        assert pay(client, amount=amount).status_code == 422


class TestIdempotency:
    def test_same_key_first_answer_even_for_another_scenario(self, client, sent):
        ik = f"k-{uuid.uuid4()}"
        a = ok(pay(client, idempotency_key=ik), role="hold")
        b = pay(client, "test_decline", idempotency_key=ik).json()
        assert a == b and len(roles(sent, 2, timeout=0.3)) == 1

    def test_idempotent_refund_books_once(self, client):
        pid = ok(pay(client, capture=True))["provider_id"]
        body = {"provider_id": pid, "amount": "40.00", "idempotency_key": "refund-1"}
        assert call(client, "refund", body).json() == call(client, "refund", body).json()
        ok(call(client, "refund", {"provider_id": pid, "amount": "60.00"}), role="refunded")


class TestCards:
    def test_bind_pay_unbind(self, client):
        b = ok(call(client, "bind", {"payment_method": "test_ok"}))
        pm = b["payment_method"]["id"]
        assert pm.startswith("pm_") and b["payment_method"]["card"]["last4"] == "0000"
        ok(pay(client, pm, capture=True), role="paid")
        ok(call(client, "unbind", {"payment_method": pm}))
        ok(call(client, "unbind", {"payment_method": pm}), outcome="declined")
        ok(pay(client, pm), outcome="declined")

    def test_a_saved_decline_card_declines(self, client):
        ok(call(client, "bind", {"payment_method": "test_decline"}), outcome="declined")


class TestNotify:
    def test_body_and_renotify_repeats_the_same_event(self, client, sent):
        pid = ok(pay(client))["provider_id"]
        r = client.post(f"/test/renotify/{pid}", headers={"X-Service-Key": KEY})
        assert r.status_code == 200
        assert len(roles(sent, 2)) == 2 and sent[0] == sent[1]
        n = sent[0].model_dump(mode="json")
        assert set(n) == {"event_id", "provider_id", "payment", "role", "provider_status", "raw"}

    def test_renotify_of_an_unknown_payment_is_404(self, client):
        assert client.post("/test/renotify/tp_none", headers={"X-Service-Key": KEY}).status_code == 404

    def test_delay_is_honoured(self, client, sent):
        t0 = time.monotonic()
        call(client, "pay", {"payment": "p", "amount": "1", "payment_method": "test_ok",
                             "metadata": {"notify_delay_ms": 300}})
        assert sent == []
        while not sent and time.monotonic() - t0 < 3:
            time.sleep(0.05)
        assert sent and time.monotonic() - t0 >= 0.3
