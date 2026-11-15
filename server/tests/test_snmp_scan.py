"""Unit test SNMP client (fake agent via UDP) + parser range/IP group.

Tidak butuh perangkat nyata: fake agent menjawab GET/GETNEXT dari tree kecil,
sehingga encode/decode BER, timeout, dan walk benar-benar dieksekusi.
"""
import socket
import threading
import time
import unittest

from app import snmp
from app.scanner import (ScanError, collect_bridge_fdb, expand_hosts, guess_model,
                         guess_vendor, normalize_range, parse_fdb_index, parse_ranges,
                         probe_host)

TREE = {
    "1.3.6.1.2.1.1.1.0": "Test switch, firmware 1.0",
    "1.3.6.1.2.1.1.2.0": "1.3.6.1.4.1.9.1.1208",
    "1.3.6.1.2.1.1.5.0": "SW-TEST-01",
    "1.3.6.1.2.1.2.2.1.2.1": "Gi0/1",
    "1.3.6.1.2.1.2.2.1.2.2": "Gi0/2",
    "1.3.6.1.4.1.9.9.9.0": "Cisco extra",
    # port map: bridge port → ifIndex, nama interface
    "1.3.6.1.2.1.17.1.4.1.2.1": 1,
    "1.3.6.1.2.1.17.1.4.1.2.2": 2,
    "1.3.6.1.2.1.31.1.1.1.1.1": "Gi0/1",
    "1.3.6.1.2.1.31.1.1.1.1.2": "Gi0/2",
    # dot1dTpFdbPort: indeks = 6 oktet MAC dalam desimal
    "1.3.6.1.2.1.17.4.3.1.2.188.36.17.233.170.113": 1,   # bc:24:11:e9:aa:71
    "1.3.6.1.2.1.17.4.3.1.2.66.67.68.69.70.71": 2,       # 42:43:44:45:46:47 (printable!)
    "1.3.6.1.2.1.17.4.3.1.2.1.0.94.0.0.1": 1,            # multicast → harus dibuang
    "1.3.6.1.2.1.17.4.3.1.2.255.255.255.255.255.255": 2,  # broadcast → harus dibuang
    "1.3.6.1.2.1.17.4.3.1.3.188.36.17.233.170.113": 3,
    "1.3.6.1.2.1.17.4.3.1.3.66.67.68.69.70.71": 4,
}

DOT1Q_TREE = {
    "1.3.6.1.2.1.1.1.0": "Q bridge switch",
    "1.3.6.1.2.1.1.2.0": "1.3.6.1.4.1.9.1.1208",
    "1.3.6.1.2.1.1.5.0": "SW-VLAN-01",
    "1.3.6.1.2.1.17.1.4.1.2.5": 5,
    "1.3.6.1.2.1.31.1.1.1.1.5": "Gi1/0/5",
    "1.3.6.1.2.1.17.7.1.4.2.1.3.10": 100,   # VLAN 10 → fdb-id 100
    "1.3.6.1.2.1.17.7.1.2.2.1.2.100.188.36.17.233.170.113": 5,
    "1.3.6.1.2.1.17.7.1.2.2.1.3.100.188.36.17.233.170.113": 3,
}


def _encode_value(value):
    if isinstance(value, int):
        return snmp.enc_int(value)
    return snmp.enc_str(str(value))


def _oid_sort_key(oid: str):
    return [int(p) for p in oid.split(".")]


class FakeAgent(threading.Thread):
    """Agen SNMP v2c kecil: menjawab GET, GETNEXT, dan GETBULK dari satu TREE."""

    def __init__(self, tree=None):
        super().__init__(daemon=True)
        self.tree = TREE if tree is None else tree
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

    def _respond(self, data: bytes) -> bytes | None:
        _tag, payload, _ = snmp._read_tlv(data, 0)
        items = snmp._seq_items(payload)
        version = int.from_bytes(items[0][1], "big")
        community = items[1][1]
        pdu_tag, pdu = items[2]
        parts = snmp._seq_items(pdu)
        request_id = parts[0][1]
        max_rep = int.from_bytes(parts[2][1], "big", signed=True)
        requested = [snmp.dec_oid(oid_payload) for tag, oid_payload in snmp._seq_items(parts[3][1])
                     if tag == 0x30
                     for _t, oid_payload in [snmp._seq_items(oid_payload)[0]]]

        varbinds = []
        if pdu_tag == snmp.GET:
            for oid in requested:
                if oid in self.tree:
                    varbinds.append(snmp._tlv(0x30, snmp.enc_oid(oid)
                                              + _encode_value(self.tree[oid])))
                else:
                    varbinds.append(snmp._tlv(0x30, snmp.enc_oid(oid) + snmp._tlv(0x81, b"")))
        elif pdu_tag in (snmp.GETNEXT, snmp.GETBULK):
            current = requested[0]
            later = sorted((o for o in self.tree if _oid_sort_key(o) > _oid_sort_key(current)),
                           key=_oid_sort_key)
            limit = 1 if pdu_tag == snmp.GETNEXT else max(max_rep, 1)
            chosen = later[:limit]
            if not chosen:
                varbinds.append(snmp._tlv(0x30, snmp.enc_oid(current) + snmp._tlv(0x82, b"")))
            for nxt in chosen:
                varbinds.append(snmp._tlv(0x30, snmp.enc_oid(nxt) + _encode_value(self.tree[nxt])))
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


class BulkWalkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = FakeAgent()
        cls.agent.start()

    @classmethod
    def tearDownClass(cls):
        cls.agent.stop()

    def client(self, version=2, timeout=0.5):
        return snmp.SnmpClient("127.0.0.1", "public", port=self.agent.port,
                               version=version, timeout=timeout)

    def test_walk_bulk_same_as_getnext(self):
        rows = self.client().walk_bulk("1.3.6.1.2.1.2.2.1.2", max_rows=10, max_repetitions=5)
        self.assertEqual([r.value for r in rows], ["Gi0/1", "Gi0/2"])

    def test_walk_bulk_respects_cap(self):
        rows = self.client().walk_bulk("1.3.6.1.2.1.2.2.1.2", max_rows=1, max_repetitions=5)
        self.assertEqual(len(rows), 1)

    def test_walk_bulk_v1_uses_getnext(self):
        rows = self.client(version=1).walk_bulk("1.3.6.1.2.1.2.2.1.2", max_rows=10,
                                                max_repetitions=5)
        self.assertEqual([r.value for r in rows], ["Gi0/1", "Gi0/2"])


class PortMapTest(unittest.TestCase):
    """BRIDGE-MIB parsing: MAC dari indeks OID, bukan dari decode OCTET STRING."""
    FDB = snmp.DOT1D_TP_FDB_PORT
    QFDB = snmp.DOT1Q_TP_FDB_PORT

    def test_parse_dot1d(self):
        oid = f"{self.FDB}.188.36.17.233.170.113"
        self.assertEqual(parse_fdb_index(oid, self.FDB), (0, "bc:24:11:e9:aa:71"))

    def test_parse_printable_mac(self):
        # oktet MAC yang kebetulan printable (0x41='A' ...) harus tetap benar
        oid = f"{self.FDB}.66.67.68.69.70.71"
        self.assertEqual(parse_fdb_index(oid, self.FDB), (0, "42:43:44:45:46:47"))

    def test_parse_dot1q_vlan(self):
        oid = f"{self.QFDB}.100.188.36.17.233.170.113"
        self.assertEqual(parse_fdb_index(oid, self.QFDB), (100, "bc:24:11:e9:aa:71"))

    def test_multicast_and_broadcast_rejected(self):
        self.assertIsNone(parse_fdb_index(f"{self.FDB}.1.0.94.0.0.1", self.FDB))
        self.assertIsNone(parse_fdb_index(f"{self.FDB}.255.255.255.255.255.255", self.FDB))
        self.assertIsNone(parse_fdb_index(f"{self.FDB}.0.0.0.0.0.0", self.FDB))

    def test_other_subtree_rejected(self):
        self.assertIsNone(parse_fdb_index(f"{self.FDB}.188.36", self.FDB))
        self.assertIsNone(parse_fdb_index("1.3.6.1.2.1.2.2.1.2.1", self.FDB))


class BridgeCollectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = FakeAgent()
        cls.agent.start()
        cls.q_agent = FakeAgent(DOT1Q_TREE)
        cls.q_agent.start()

    @classmethod
    def tearDownClass(cls):
        cls.agent.stop()
        cls.q_agent.stop()

    def client(self, agent=None, timeout=0.5):
        agent = agent or self.agent
        return snmp.SnmpClient("127.0.0.1", "public", port=agent.port, timeout=timeout)

    def test_collect_dot1d(self):
        bridge = collect_bridge_fdb(self.client(), max_rows=100)
        self.assertEqual(bridge["kind"], "dot1d")
        self.assertFalse(bridge["truncated"])
        by_mac = {r["mac"]: r for r in bridge["rows"]}
        self.assertEqual(set(by_mac), {"bc:24:11:e9:aa:71", "42:43:44:45:46:47"})
        self.assertEqual(by_mac["bc:24:11:e9:aa:71"]["if_name"], "Gi0/1")
        self.assertEqual(by_mac["bc:24:11:e9:aa:71"]["bridge_port"], 1)
        self.assertEqual(by_mac["bc:24:11:e9:aa:71"]["status"], "learned")
        self.assertEqual(by_mac["42:43:44:45:46:47"]["if_name"], "Gi0/2")
        self.assertEqual(by_mac["42:43:44:45:46:47"]["status"], "self")
        self.assertEqual(bridge["ports"], 2)

    def test_collect_truncated(self):
        bridge = collect_bridge_fdb(self.client(), max_rows=2)
        self.assertTrue(bridge["truncated"])
        self.assertEqual(bridge["count"], 1)   # satu baris multicast dibuang

    def test_collect_dot1q_fallback(self):
        bridge = collect_bridge_fdb(self.client(self.q_agent), max_rows=100)
        self.assertEqual(bridge["kind"], "dot1q")
        self.assertEqual(bridge["count"], 1)
        row = bridge["rows"][0]
        self.assertEqual(row["mac"], "bc:24:11:e9:aa:71")
        self.assertEqual(row["vlan"], 10)          # fdb-id 100 dipetakan ke VLAN 10
        self.assertEqual(row["if_name"], "Gi1/0/5")
        self.assertEqual(row["bridge_port"], 5)

    def test_probe_host_includes_port_map(self):
        result = probe_host("127.0.0.1", community="public", version=2,
                            port=self.agent.port, timeout=0.5, retries=0,
                            custom_oids=[], collect_fdb=True, fdb_max=100)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bridge"]["kind"], "dot1d")
        self.assertEqual(len(result["fdb"]), 2)
        self.assertEqual(result["oid_values"], {})

    def test_probe_host_can_disable_port_map(self):
        result = probe_host("127.0.0.1", community="public", version=2,
                            port=self.agent.port, timeout=0.5, retries=0,
                            custom_oids=[], collect_fdb=False)
        self.assertEqual(result["fdb"], [])
        self.assertIsNone(result["bridge"]["kind"])


if __name__ == "__main__":
    unittest.main()