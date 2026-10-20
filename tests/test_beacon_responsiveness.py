import asyncio
import threading

from app.mobile import lan_beacon


PAYLOAD = {"https": "https://192.168.1.12:4781", "server_pin": "a" * 64}


def test_announcements_never_trigger_a_reply():
    def unexpected(peer=""):
        raise AssertionError("A server announcement must not trigger a new announcement")
    proto = lan_beacon._BeaconProtocol(unexpected)
    proto.datagram_received(lan_beacon.encode_beacon(PAYLOAD), ("192.168.1.12", 4782))
    proto.datagram_received(lan_beacon.encode_beacon(PAYLOAD), ("192.168.1.99", 4782))


def test_probe_payload_and_route_checks_run_off_loop(monkeypatch):
    main = threading.get_ident()
    calls = []
    def payload(peer=""):
        assert threading.get_ident() != main
        calls.append(peer)
        return PAYLOAD
    def route(peer):
        assert threading.get_ident() != main
        return ""
    monkeypatch.setattr(lan_beacon, "beacon_reply_source", route)
    replies = []
    proto = lan_beacon._BeaconProtocol(payload)
    proto._transport = type("Transport", (), {"sendto": lambda self, blob, addr: replies.append((blob, addr))})()
    async def run():
        proto.datagram_received(b'{"probe":true}', ("192.168.1.40", 54321))
        await asyncio.gather(*proto._reply_tasks)
    asyncio.run(run())
    assert calls == ["192.168.1.40"]
    assert replies[0][1] == ("192.168.1.40", 54321)
    assert lan_beacon.parse_beacon(replies[0][0])["server_pin"] == "a" * 64


def test_broadcast_work_is_off_loop_and_closes(monkeypatch):
    main = threading.get_ident()
    def plan():
        assert threading.get_ident() != main
        return []
    def payload(peer=""):
        assert threading.get_ident() != main
        return PAYLOAD
    monkeypatch.setattr(lan_beacon, "beacon_send_plan", plan)
    async def run():
        sent = asyncio.Event()
        class Transport:
            def sendto(self, blob, addr):
                assert threading.get_ident() == main
                assert lan_beacon.parse_beacon(blob)
                sent.set()
        proto = lan_beacon._BeaconProtocol(payload)
        proto._transport = Transport()
        proto._broadcast_task = asyncio.create_task(proto._broadcast_loop())
        task = proto._broadcast_task
        await asyncio.wait_for(sent.wait(), 2)
        proto.close()
        await task
        assert proto._closed
    asyncio.run(run())
