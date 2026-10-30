"""Real LevelDB WAL fixtures exercise current-session selection without secrets."""

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fupload_cli.modus import load_current_build, load_main_session
from fupload_cli.errors import FuploadError


ORIGIN = "http://tongji.modus.cool"


def varint(value):
    data = bytearray()
    while value >= 128:
        data.append((value & 127) | 128)
        value >>= 7
    return bytes(data + bytes([value]))


def crc32c(data):
    crc = 0xffffffff
    for value in data:
        crc ^= value
        for _ in range(8): crc = (crc >> 1) ^ (0x82f63b78 if crc & 1 else 0)
    crc ^= 0xffffffff
    return ((crc >> 15) | (crc << 17)) + 0xa282ead8 & 0xffffffff


def record(data):
    tagged = b"\x01" + data
    return struct.pack("<IHB", crc32c(tagged), len(data), 1) + data


def key(name, origin=ORIGIN):
    return b"_" + origin.encode() + b"\x00\x01" + name.encode()


def value(document, utf16=False):
    text = json.dumps(document, ensure_ascii=False)
    return b"\x00" + text.encode("utf-16-le") if utf16 else b"\x01" + text.encode("latin1")


def batch(sequence, entries):
    data = struct.pack("<QI", sequence, len(entries))
    for storage_key, storage_value in entries:
        data += (b"\x00" if storage_value is None else b"\x01") + varint(len(storage_key)) + storage_key
        if storage_value is not None: data += varint(len(storage_value)) + storage_value
    return record(data)


def fixture(root, entries):
    leveldb = root / "Local Storage" / "leveldb"
    leveldb.mkdir(parents=True)
    (leveldb / "CURRENT").write_bytes(b"MANIFEST-000001\n")
    (leveldb / "MANIFEST-000001").write_bytes(record(b"\x02" + varint(4) + b"\x09\x00"))
    (leveldb / "000004.log").write_bytes(batch(20, entries))
    return leveldb


def table(entries, compressed=False):
    def block(rows):
        data = b""
        for storage_key, storage_value in rows:
            data += b"\x00" + varint(len(storage_key)) + varint(len(storage_value)) + storage_key + storage_value
        data += struct.pack("<II", 0, 1)
        if compressed:
            size = len(data) - 1
            if size < 60: literal = bytes([size << 2])
            else:
                raw_size = size.to_bytes((size.bit_length() + 7) // 8, "little")
                literal = bytes([(59 + len(raw_size)) << 2]) + raw_size
            data = varint(len(data)) + literal + data
        kind = b"\x01" if compressed else b"\x00"
        return data + kind + struct.pack("<I", crc32c(data + kind)), len(data)
    internal = [(storage_key + struct.pack("<Q", (sequence << 8) | (0 if storage_value is None else 1)), storage_value or b"") for sequence, storage_key, storage_value in entries]
    data_block, data_size = block(internal)
    handle = varint(0) + varint(data_size)
    index_block, index_size = block([(b"last", handle)])
    footer = b"\x00\x00" + varint(len(data_block)) + varint(index_size)
    return data_block + index_block + footer.ljust(40, b"\x00") + bytes.fromhex("57fb808b247547db")


def add_table(leveldb, number, data):
    (leveldb / ("%06d.ldb" % number)).write_bytes(data)
    edit = b"\x07\x00" + varint(number) + varint(len(data)) + b"\x00\x00"
    with (leveldb / "MANIFEST-000001").open("ab") as manifest: manifest.write(record(edit))


class LevelDBAuthTests(unittest.TestCase):
    def test_latest_wal_session_overrides_obsolete_table_and_older_wal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leveldb = fixture(root, [(key("user"), value({"token": "CURRENT-FIXTURE"})), (key("app"), value({"deviceId": "DEVICE"}))])
            (leveldb / "000003.ldb").write_bytes(b'{"token":"OBSOLETE-FIXTURE","deviceId":"OLD-DEVICE"}')
            (leveldb / "000002.log").write_bytes(batch(3, [(key("user"), value({"token": "OLD-WAL"}))]))
            self.assertEqual(load_main_session(root), {"token": "CURRENT-FIXTURE", "device_id": "DEVICE"})

    def test_tombstone_and_explicit_logout_do_not_restore_historical_token(self):
        for replacement in (None, value({"token": ""})):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                leveldb = fixture(root, [(key("user"), value({"token": "OLD"})), (key("user"), replacement)])
                with self.assertRaises(FuploadError): load_main_session(root)

    def test_unrelated_origin_and_nested_tokens_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root, [(key("user", "https://unrelated.invalid"), value({"token": "WRONG"})), (key("other"), value({"token": "OTHER"})), (key("user"), value({"wallet": {"token": "NESTED"}}))])
            with self.assertRaises(FuploadError): load_main_session(root)

    def test_utf16_user_json_and_build_take_latest_sequence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root, [(key("wow"), value({"currentGameWow": {"id": 1}})), (key("user"), value({"token": "CURRENT", "nickName": "测试", "wallet": {"balance": 0}}, utf16=True)), (key("wow"), value({"currentGameWow": {"id": 4}}))])
            self.assertEqual(load_main_session(root), {"token": "CURRENT"})
            self.assertEqual(load_current_build(root), 4)

    def test_current_sst_and_snappy_values_are_read_by_internal_sequence(self):
        for compressed in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                leveldb = fixture(root, [])
                add_table(leveldb, 3, table([(5, key("user"), value({"token": "TABLE-CURRENT"})), (6, key("app"), value({"deviceId": "DEVICE"})), (7, key("wow"), value({"currentGameWow": {"id": 3}}))], compressed))
                self.assertEqual(load_main_session(root), {"token": "TABLE-CURRENT", "device_id": "DEVICE"})
                self.assertEqual(load_current_build(root), 3)

    def test_wal_tombstone_overrides_live_sst_and_manifest_drops_old_table(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leveldb = fixture(root, [(key("user"), None)])
            add_table(leveldb, 3, table([(5, key("user"), value({"token": "TABLE-OLD"}))]))
            with self.assertRaises(FuploadError): load_main_session(root)
            with (leveldb / "MANIFEST-000001").open("ab") as manifest: manifest.write(record(b"\x06\x00\x03"))
            (leveldb / "000004.log").write_bytes(batch(30, [(key("app"), value({"deviceId": "DEVICE"}))]))
            with self.assertRaises(FuploadError): load_main_session(root)

    def test_fragmented_wal_record_is_reassembled_and_partial_tail_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leveldb = fixture(root, [])
            document = value({"token": "CURRENT", "wallet": {"padding": "x" * 40000}})
            logical = struct.pack("<QI", 30, 1) + b"\x01" + varint(len(key("user"))) + key("user") + varint(len(document)) + document
            first, last = logical[:32761], logical[32761:]
            physical = struct.pack("<IHB", crc32c(b"\x02" + first), len(first), 2) + first
            physical += struct.pack("<IHB", crc32c(b"\x04" + last), len(last), 4) + last
            physical += record(struct.pack("<QI", 40, 1) + b"\x00" + varint(len(key("user"))) + key("user"))[:-3]
            (leveldb / "000004.log").write_bytes(physical)
            self.assertEqual(load_main_session(root), {"token": "CURRENT"})

    def test_corrupt_current_wal_never_falls_back_to_old_table_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leveldb = fixture(root, [(key("user"), value({"token": "CURRENT"}))])
            add_table(leveldb, 3, table([(5, key("user"), value({"token": "TABLE-OLD"}))]))
            path = leveldb / "000004.log"
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
            with self.assertRaises(FuploadError): load_main_session(root)

    def test_sequence_order_overrides_filename_order_and_deleted_wow_is_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            leveldb = fixture(root, [(key("user"), value({"token": "NEWEST"})), (key("wow"), None)])
            (leveldb / "000005.log").write_bytes(batch(3, [(key("user"), value({"token": "OLDER-SEQUENCE"}))]))
            add_table(leveldb, 3, table([(5, key("wow"), value({"currentGameWow": {"id": 1}}))]))
            self.assertEqual(load_main_session(root), {"token": "NEWEST"})
            self.assertIsNone(load_current_build(root))


if __name__ == "__main__": unittest.main()
