from apc40sonar import seq_link


class FakeSocket:
    def __init__(self, incoming=()):
        self.sent = []
        self.incoming = list(incoming)

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recv(self, size):
        if not self.incoming:
            raise BlockingIOError
        return self.incoming.pop(0)

    def close(self):
        pass


def test_encode_decode_round_trip():
    data = seq_link.encode("cmd", {"op": "cycle", "lane": 1, "step": 2})

    assert seq_link.decode(data, "cmd") == {"op": "cycle", "lane": 1, "step": 2}
    assert seq_link.decode(data, "state") is None
    assert seq_link.decode(b"junk", "cmd") is None


def test_receiver_returns_every_command_in_order():
    sock = FakeSocket([seq_link.encode("cmd", {"op": "a"}), b"junk", seq_link.encode("cmd", {"op": "b"})])

    assert seq_link.Receiver(0, sock=sock).poll("cmd") == [{"op": "a"}, {"op": "b"}]


def test_publisher_sends_changes_rate_capped_and_heartbeats():
    now = [0.0]
    sock = FakeSocket()
    pub = seq_link.StatePublisher(seq_link.Sender(47041, sock=sock), clock=lambda: now[0])

    assert pub.publish({"x": 1})
    assert not pub.publish({"x": 2})  # within the rate cap
    now[0] = 0.1
    assert pub.publish({"x": 2})
    now[0] = 0.5
    assert not pub.publish({"x": 2})  # unchanged
    now[0] = 1.2
    assert pub.publish({"x": 2})  # heartbeat
    pub.reset()
    assert pub.publish({"x": 2})
    assert len(sock.sent) == 4
