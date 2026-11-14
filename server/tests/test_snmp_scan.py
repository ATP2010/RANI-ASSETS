"""Unit test SNMP client (fake agent via UDP) + parser range/IP group.

Tidak butuh perangkat nyata: fake agent menjawab GET/GETNEXT dari tree kecil,
sehingga encode/decode BER, timeout, dan walk benar-benar dieksekusi.
"""
import socket
import threading
import time
import unittest

from app import snmp
from app.scanner import ScanError, expand_hosts, guess_model, guess_vendor, normalize_range, \
    parse_ranges

TREE = {
    "1.3.6.1.2.1.1.1.0": "Test switch, firmware 1.0",
    "1.3.6.1.2.1.1.2.0": "1.3.6.1.4.1.9.1.1208",
    "1.3.6.1.2.1.1.5.0": "SW-TEST-01",
    "1.3.6.1.2.1.2.2.1.2.1": "Gi0/1",
    "1.3.6.1.2.1.2.2.1.2.2": "Gi0/2",
    "1.3.6.1.4.1.9.9.9.0": "Cisco extra",
}


def _encode_value(value):
    if isinstance(value, int):
        return snmp.enc_int(value)
    return snmp.enc_str(str(value))


def _oid_sort_key(oid: str):
    return [int(p) for p in oid.split(".")]


class FakeAgent(threading.Thread):
    """Agen SNMP v2c kecil: menjawab GET (daftar OID) dan GETNEXT (satu OID)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.requests = 0
        self._stop_evt = threading.Event()   # jangan pakai nama _stop: milik Thread

    def run(self):
        self.sock.settimeout(0.2)
        while not self._stop_evt.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                reply = self._respond(data)
            except Exception:  # noqa: BLE001 — tes: paket rusak diabaikan
                continue
            if reply:
                self.requests += 1
                self.sock.sendto(reply, addr)

    def stop(self):
        self._stop_evt.set()
        self.sock.close()

    @staticmethod
    def _respond(data: bytes) -> bytes | None:
        _tag, payload, _ = snmp._read_tlv(data, 0)
        items = snmp._seq_items(payload)
        version = int.from_bytes(items[0][1], "big")
        community = items[1][1]
        pdu_tag, pdu = items[2]
        parts = snmp._seq_items(pdu)
        request_id = parts[0][1]
        requested = [snmp.dec_oid(oid_payload) for tag, oid_payload in snmp._seq_items(parts[3][1])
                     if tag == 0x30
                     for _t, oid_payload in [snmp._seq_items(oid_payload)[0]]]

        varbinds = []
        if pdu_tag == snmp.GET:
            for oid in requested:
                if oid in TREE:
                    varbinds.append(snmp._tlv(0x30, snmp.enc_oid(oid)
                                              + _encode_value(TREE[oid])))
                else:
                    varbinds.append(snmp._tlv(0x30, snmp.enc_oid(oid) + snmp._tlv(0x81, b"")))
        elif pdu_tag == snmp.GETNEXT:
            current = requested[0]
            later = sorted((o for o in TREE if _oid_sort_key(o) > _oid_sort_key(current)),
                           key=_oid_sort_key)
            if later:
                nxt = later[0]
                varbinds.append(snmp._tlv(0x30, snmp.enc_oid(nxt) + _encode_value(TREE[nxt])))
            else:
                varbinds.append(snmp._tlv(0x30, snmp.enc_oid(current) + snmp._tlv(0x82, b"")))
        else:
            return None

        response = snmp._tlv(0xA2, snmp._tlv(0x02, request_id) + snmp.enc_int(0)
                             + snmp.enc_int(0) + snmp._tlv(0x30, b"".join(varbinds)))
        message = snmp._tlv(0x30, snmp.enc_int(version) + snmp.enc_str(community.decode())
                            + response)
        return message


class BerTest(unittest.TestCase):
    def test_oid_roundtrip(self):
        for oid in ("1.3.6.1.2.1.1.1.0", "1.3.6.1.4.1.9.1.1208", "1.3.6.1.2.1.2.2.1.2.42"):
            encoded = snmp.enc_oid(oid)
            tag, payload, _ = snmp._read_tlv(encoded, 0)
            self.assertEqual(tag, 0x06)
            self.assertEqual(snmp.dec_oid(payload), oid)

    def test_message_version_field(self):
        # v2c harus dikodekan sebagai version=1, v1 sebagai 0 (bug klasik: v2c ditulis 2)
        client = snmp.SnmpClient("127.0.0.1", "public")
        _, packet = client._packet(snmp.GET, [snmp.SYS_DESCR])
        tag, payload, _ = snmp._read_tlv(packet, 0)
        items = snmp._seq_items(payload)
        self.assertEqual(int.from_bytes(items[0][1], "big"), 1)
        v1 = snmp.SnmpClient("127.0.0.1", "public", version=1)
        _, packet = v1._packet(snmp.GET, [snmp.SYS_DESCR])
        tag, payload, _ = snmp._read_tlv(packet, 0)
        self.assertEqual(int.from_bytes(snmp._seq_items(payload)[0][1], "big"), 0)

    def test_integer_encoding_positive_high_bit(self):
        encoded = snmp.enc_int(200)
        self.assertEqual(encoded, b"\x02\x02\x00\xc8")


class ClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = FakeAgent()
        cls.agent.start()

    @classmethod
    def tearDownClass(cls):
        cls.agent.stop()

    def client(self, timeout=0.5):
        return snmp.SnmpClient("127.0.0.1", "public", port=self.agent.port, timeout=timeout)

    def test_get_many(self):
        values = self.client().get_many([snmp.SYS_DESCR, snmp.SYS_OBJECT_ID, "1.3.6.1.2.1.1.9.0"])
        self.assertEqual(values[snmp.SYS_DESCR], "Test switch, firmware 1.0")
        self.assertEqual(values[snmp.SYS_OBJECT_ID], "1.3.6.1.4.1.9.1.1208")
        self.assertIsNone(values["1.3.6.1.2.1.1.9.0"])  # noSuchInstance

    def test_walk_subtree(self):
        rows = self.client().walk("1.3.6.1.2.1.2.2.1.2", max_rows=10)
        self.assertEqual([r.value for r in rows], ["Gi0/1", "Gi0/2"])
        self.assertTrue(all(r.oid.startswith("1.3.6.1.2.1.2.2.1.2.") for r in rows))

    def test_timeout_raises(self):
        silent = snmp.SnmpClient("127.0.0.1", "public", port=1, timeout=0.1, retries=0)
        started = time.time()
        with self.assertRaises(snmp.SnmpError):
            silent.get(snmp.SYS_DESCR)
        self.assertLess(time.time() - started, 2)


class RangeTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_range("10.0.0.5"), "10.0.0.5")
        self.assertEqual(normalize_range("10.0.0.9/24"), "10.0.0.0/24")
        self.assertEqual(normalize_range("10.0.0.5 - 10.0.0.9"), "10.0.0.5-10.0.0.9")
        with self.assertRaises(ScanError):
            normalize_range("10.0.0.300")
        with self.assertRaises(ScanError):
            normalize_range("2001:db8::1")

    def test_parse_and_expand(self):
        ranges = parse_ranges(["10.0.0.0/30, 10.0.1.7", "10.0.2.1-10.0.2.3"])
        self.assertEqual(ranges, ["10.0.0.0/30", "10.0.1.7", "10.0.2.1-10.0.2.3"])
        hosts, truncated = expand_hosts(ranges, 100)
        self.assertEqual(hosts, ["10.0.0.1", "10.0.0.2", "10.0.1.7",
                                 "10.0.2.1", "10.0.2.2", "10.0.2.3"])
        self.assertFalse(truncated)
        hosts, truncated = expand_hosts(["10.0.0.0/24"], 10)
        self.assertEqual(len(hosts), 10)
        self.assertTrue(truncated)

    def test_vendor_and_model_guess(self):
        self.assertEqual(guess_vendor("1.3.6.1.4.1.9.1.1208", "Cisco IOS"), "Cisco")
        self.assertEqual(guess_vendor("1.3.6.1.4.1.99999.1", "ZyXEL switch"), "ZyXEL")
        self.assertEqual(guess_model("Cisco IOS Software, C2960X Software", None), "C2960X")
        self.assertEqual(guess_model("anything", "Catalyst 9300"), "Catalyst 9300")


if __name__ == "__main__":
    unittest.main()