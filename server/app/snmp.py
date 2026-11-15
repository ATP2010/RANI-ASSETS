"""SNMP v1/v2c client minimal (stdlib saja) untuk fitur Scan.

Kenapa tidak pakai pysnmp: agent/collector project ini stdlib-first, dan kebutuhan scan
hanya GET/GETNEXT (sysObjectID, sysDescr, sysName, serial, ifNumber, custom OID).
Implementasi ini menangani:
- BER encode/decode (INTEGER, OCTET STRING, NULL, OID, IpAddress, Counter/Gauge/TimeTicks,
  Counter64, varbind exception noSuchObject/noSuchInstance/endOfMibView)
- GET multi-varbind (satu paket untuk banyak OID) dan GETNEXT (walk subtree, dibatasi)
- timeout + retry, dan error SNMP (error-status != 0) sebagai SnmpError

Dipakai lewat `ServerProbe` di app/scanner.py; dijalankan di thread (socket blocking).
"""
from __future__ import annotations

import logging
import random
import socket
from dataclasses import dataclass

log = logging.getLogger("rani.snmp")

GET = 0xA0
GETNEXT = 0xA1
RESPONSE = 0xA2
GETBULK = 0xA5

# varbind exceptions (SNMPv2)
EXCEPTIONS = {0x80: "noSuchObject", 0x81: "noSuchInstance", 0x82: "endOfMibView"}

ERRORS = {1: "tooBig", 2: "noSuchName", 3: "badValue", 4: "readOnly", 5: "genErr"}

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
IF_NUMBER = "1.3.6.1.2.1.2.1.0"
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
IF_HC_IN_OCTETS = "1.3.6.1.2.1.31.1.1.1.6"
ENTITY_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
ENTITY_MODEL = "1.3.6.1.2.1.47.1.1.1.1.2"
ENTITY_VENDOR = "1.3.6.1.2.1.47.1.1.1.1.12"

# BRIDGE-MIB / Q-BRIDGE-MIB: MAC-per-port (tabel forwarding switch).
# Indeks dot1dTpFdbPort = 6 oktet MAC; indeks dot1qTpFdbPort = fdb-id + 6 oktet MAC.
DOT1D_TP_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
DOT1D_TP_FDB_STATUS = "1.3.6.1.2.1.17.4.3.1.3"
DOT1D_BASE_PORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
DOT1Q_TP_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"
DOT1Q_TP_FDB_STATUS = "1.3.6.1.2.1.17.7.1.2.2.1.3"
DOT1Q_VLAN_FDB_ID = "1.3.6.1.2.1.17.7.1.4.2.1.3"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"

FDB_STATUS = {1: "other", 2: "invalid", 3: "learned", 4: "self", 5: "mgmt"}


class SnmpError(RuntimeError):
    pass


# ------------------------------------------------------------------------- BER --
def _enc_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _enc_len(len(payload)) + payload


def _enc_uint(value: int) -> bytes:
    if value == 0:
        return b"\x00"
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return raw


def enc_int(value: int) -> bytes:
    return _tlv(0x02, _enc_uint(value))


def enc_str(value: str) -> bytes:
    return _tlv(0x04, value.encode("utf-8", "replace"))


def enc_null() -> bytes:
    return _tlv(0x05, b"")


def enc_oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.strip(".").split(".") if p != ""]
    if len(parts) < 2:
        raise SnmpError(f"OID tidak valid: {oid}")
    out = bytearray([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        if part < 0x80:
            out.append(part)
            continue
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append((part & 0x7F) | 0x80)
            part >>= 7
        out.extend(reversed(chunk))
    return _tlv(0x06, bytes(out))


def dec_oid(payload: bytes) -> str:
    if not payload:
        return ""
    first = payload[0]
    parts = [first // 40, first % 40]
    value = 0
    for byte in payload[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(str(p) for p in parts)


def _read_tlv(data: bytes, offset: int) -> tuple[int, bytes, int]:
    if offset >= len(data):
        raise SnmpError("paket SNMP terpotong")
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[offset:offset + count], "big")
        offset += count
    if offset + length > len(data):
        raise SnmpError("panjang TLV melebihi paket")
    return tag, data[offset:offset + length], offset + length


def _seq_items(payload: bytes) -> list[tuple[int, bytes]]:
    items, offset = [], 0
    while offset < len(payload):
        tag, value, offset = _read_tlv(payload, offset)
        items.append((tag, value))
    return items


def _dec_value(tag: int, payload: bytes):
    if tag in EXCEPTIONS:
        return None
    if tag == 0x02:  # INTEGER
        return int.from_bytes(payload, "big", signed=True)
    if tag in (0x41, 0x42, 0x43, 0x46):  # Counter32/Gauge32/TimeTicks/Counter64
        return int.from_bytes(payload, "big", signed=False)
    if tag == 0x04:  # OCTET STRING
        try:
            return payload.decode("utf-8").replace("\x00", "").strip()
        except UnicodeDecodeError:
            return payload.hex()
    if tag == 0x06:
        return dec_oid(payload)
    if tag == 0x40:  # IpAddress
        return ".".join(str(b) for b in payload)
    if tag == 0x05:
        return None
    return payload.hex()


# ---------------------------------------------------------------------- client --
@dataclass
class VariBind:
    oid: str
    value: object


class SnmpClient:
    """SNMP v1/v2c client sederhana untuk satu perangkat."""

    def __init__(self, host: str, community: str, *, port: int = 161, version: int = 2,
                 timeout: float = 1.0, retries: int = 1) -> None:
        self.host = host
        self.community = community
        self.port = port
        # SNMP version field: 0 = v1, 1 = v2c (bukan 2!)
        self.version = 0 if version == 1 else 1
        self.timeout = timeout
        self.retries = max(retries, 0)
        self._request_id = random.randint(1, 0x7FFFFFFF)

    # -- wire ---------------------------------------------------------------
    def _packet(self, pdu_tag: int, oids: list[str],
                max_repetitions: int = 0) -> tuple[int, bytes]:
        self._request_id = (self._request_id + 1) & 0x7FFFFFFF
        varbinds = b"".join(_tlv(0x30, enc_oid(oid) + enc_null()) for oid in oids)
        # Field ke-2 PDU = error-status/non-repeaters, ke-3 = error-index/max-repetitions.
        second = max_repetitions if pdu_tag == GETBULK else 0
        pdu = _tlv(pdu_tag, enc_int(self._request_id) + enc_int(0) + enc_int(second)
                   + _tlv(0x30, varbinds))
        message = _tlv(0x30, enc_int(self.version) + enc_str(self.community) + pdu)
        return self._request_id, message

    def _exchange(self, packet: bytes, request_id: int) -> list[VariBind]:
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(self.timeout)
                    sock.sendto(packet, (self.host, self.port))
                    data, _addr = sock.recvfrom(65535)
                return self._parse(data, request_id)
            except (socket.timeout, TimeoutError) as exc:
                last_error = exc
            except OSError as exc:
                raise SnmpError(f"gagal kirim SNMP: {exc}") from exc
        raise SnmpError("timeout menunggu balasan SNMP") from last_error

    def _parse(self, data: bytes, request_id: int) -> list[VariBind]:
        tag, payload, _ = _read_tlv(data, 0)
        if tag != 0x30:
            raise SnmpError("balasan bukan SEQUENCE SNMP")
        items = _seq_items(payload)
        if len(items) < 3:
            raise SnmpError("balasan SNMP tidak lengkap")
        pdu_tag, pdu = items[2]
        if pdu_tag not in (RESPONSE, GET, GETNEXT):
            raise SnmpError(f"PDU tidak dikenal 0x{pdu_tag:02x}") 
        pdu_items = _seq_items(pdu)
        if len(pdu_items) < 4:
            raise SnmpError("PDU SNMP tidak lengkap")
        rid = int.from_bytes(pdu_items[0][1], "big", signed=True)
        if rid != request_id:
            raise SnmpError("request-id balasan tidak cocok")
        err_status = int.from_bytes(pdu_items[1][1], "big", signed=True)
        if err_status:
            raise SnmpError(ERRORS.get(err_status, f"error-status {err_status}"))
        out: list[VariBind] = []
        for vb_tag, vb_payload in _seq_items(pdu_items[3][1]):
            if vb_tag != 0x30:
                continue
            parts = _seq_items(vb_payload)
            if len(parts) < 2:
                continue
            oid = dec_oid(parts[0][1])
            out.append(VariBind(oid=oid, value=_dec_value(parts[1][0], parts[1][1])))
        return out

    # -- api ---------------------------------------------------------------
    def get_many(self, oids: list[str]) -> dict[str, object]:
        if not oids:
            return {}
        request_id, packet = self._packet(GET, oids)
        result = self._exchange(packet, request_id)
        return {vb.oid: vb.value for vb in result}

    def get(self, oid: str):
        return self.get_many([oid]).get(oid)

    def walk(self, base_oid: str, max_rows: int = 64) -> list[VariBind]:
        """GETNEXT dari satu root OID; berhenti saat keluar subtree / max_rows."""
        rows: list[VariBind] = []
        current = base_oid
        prefix = base_oid.rstrip(".") + "."
        for _ in range(max_rows):
            request_id, packet = self._packet(GETNEXT, [current])
            result = self._exchange(packet, request_id)
            if not result:
                break
            vb = result[0]
            if vb.value is None or not vb.oid.startswith(prefix):
                break
            rows.append(vb)
            current = vb.oid
        return rows

    def walk_bulk(self, base_oid: str, max_rows: int = 256,
                  max_repetitions: int = 15) -> list[VariBind]:
        """Walk cepat pakai GETBULK (SNMPv2c). v1 / agen bermasalah → fallback GETNEXT.

        Satu request membawa sampai `max_repetitions` baris, jadi tabel switch berisi
        ribuan MAC tidak butuh ribuan round-trip.
        """
        if self.version == 0 or max_repetitions < 1 or max_rows <= 0:
            return self.walk(base_oid, max_rows=max_rows)
        rows: list[VariBind] = []
        current = base_oid
        prefix = base_oid.rstrip(".") + "."
        while len(rows) < max_rows:
            try:
                request_id, packet = self._packet(GETBULK, [current],
                                                  max_repetitions=max_repetitions)
                result = self._exchange(packet, request_id)
            except SnmpError as exc:
                if "timeout" in str(exc):
                    raise
                # agen lama/kaku menolak GETBULK (tooBig/genErr) → pakai GETNEXT
                return rows or self.walk(base_oid, max_rows=max_rows)
            if not result:
                break
            progressed = False
            for vb in result:
                if vb.value is None or not vb.oid.startswith(prefix):
                    return rows
                if vb.oid == current:
                    continue
                rows.append(vb)
                current = vb.oid
                progressed = True
                if len(rows) >= max_rows:
                    break
            if not progressed:
                break
        return rows