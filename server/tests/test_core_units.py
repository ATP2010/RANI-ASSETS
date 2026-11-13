"""Unit test murni (tanpa DB) untuk aturan identitas, normalisasi, dan keamanan.

Jalankan di dalam image:
    docker exec rani-inv-api-1 sh -c "cd /srv && python -m unittest discover -s tests -v"
"""
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from app.ingest.reconciler import (clean_identifier, norm_software, normalize_mac,
                                   pick_primary_interface)
from app.security import (constant_eq, hash_password, hmac_hex, role_allows,
                          sha256_hex, verify_password)

SCHEMA = Path("/srv/schema/agent_payload_v1.json")


class NormalizationTest(unittest.TestCase):
    def test_mac_formats(self):
        self.assertEqual(normalize_mac("BC-24-11-E9-AA-71"), "bc:24:11:e9:aa:71")
        self.assertEqual(normalize_mac("bc2411e9aa71"), "bc:24:11:e9:aa:71")
        self.assertIsNone(normalize_mac("00:00:00:00:00:00"))
        self.assertIsNone(normalize_mac("not-a-mac"))

    def test_software_name_normalization(self):
        self.assertEqual(norm_software("  Google   Chrome  "), "google chrome")
        self.assertEqual(norm_software("7-Zip"), "7-zip")

    def test_junk_identifiers_rejected(self):
        for junk in ("", "  ", "Default string", "To be filled by O.E.M.", "None", "0"):
            self.assertIsNone(clean_identifier(junk), junk)
        self.assertEqual(clean_identifier(" SN-12345 "), "SN-12345")

    def test_primary_interface_prefers_gateway(self):
        interfaces = [
            {"name": "docker0", "mac": "02:42:ac:11:00:02", "ipv4": "172.17.0.1"},
            {"name": "eth0", "mac": "bc:24:11:e9:aa:71", "ipv4": "192.168.88.92",
             "gateway": "192.168.88.1"},
        ]
        picked = pick_primary_interface(interfaces)
        self.assertEqual(picked["name"], "eth0")


class SecurityTest(unittest.TestCase):
    def test_password_roundtrip(self):
        hashed = hash_password("rahasia-uji-123")
        self.assertTrue(verify_password("rahasia-uji-123", hashed))
        self.assertFalse(verify_password("salah", hashed))
        self.assertFalse(verify_password("apa pun", None))

    def test_hmac_and_compare(self):
        digest = hmac_hex("secret", b"payload")
        self.assertEqual(len(digest), 64)
        self.assertTrue(constant_eq(digest, digest))
        self.assertFalse(constant_eq(digest, digest[:-1]))

    def test_role_ranking(self):
        self.assertTrue(role_allows("admin", "operator"))
        self.assertTrue(role_allows("operator", "reader"))
        self.assertFalse(role_allows("reader", "operator"))
        self.assertFalse(role_allows("unknown", "reader"))

    def test_sha256(self):
        self.assertEqual(sha256_hex(b"rani"), sha256_hex("rani"))


class PayloadContractTest(unittest.TestCase):
    def setUp(self):
        if not SCHEMA.exists():
            self.skipTest("schema file tidak ada di image")
        self.validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))

    def base_payload(self):
        return {"schema_version": 1, "agent_version": "0.1.0",
                "collected_at": "2026-11-13T20:00:00Z",
                "identity": {"machine_id": "abc", "hostname": "PC-01"},
                "os": {"family": "windows", "caption": "Windows 11 Pro"}}

    def test_minimal_payload_valid(self):
        self.assertEqual(list(self.validator.iter_errors(self.base_payload())), [])

    def test_missing_os_rejected(self):
        payload = self.base_payload()
        payload.pop("os")
        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_wrong_schema_version_rejected(self):
        payload = self.base_payload()
        payload["schema_version"] = 2
        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_unknown_os_family_rejected(self):
        payload = self.base_payload()
        payload["os"]["family"] = "solaris"
        self.assertTrue(list(self.validator.iter_errors(payload)))


if __name__ == "__main__":
    unittest.main()