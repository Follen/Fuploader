"""Read current Chromium local-storage values without opening or modifying LevelDB.

CURRENT/MANIFEST selects live tables, WAL batches and SST internal keys supply
sequence numbers, and tombstones participate in the same latest-value selection.
No historical-value fallback, credential search, or database write is performed.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Dict, Iterator, Optional, Sequence, Tuple


class LevelDBReadError(ValueError):
    pass


def _varint(data: bytes, offset: int) -> Tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            break
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise LevelDBReadError("invalid LevelDB integer")


def _slice(data: bytes, offset: int) -> Tuple[bytes, int]:
    size, offset = _varint(data, offset)
    if size > len(data) - offset:
        raise LevelDBReadError("truncated LevelDB field")
    return data[offset:offset + size], offset + size


def _crc32c(data: bytes) -> int:
    crc = 0xffffffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82f63b78 if crc & 1 else 0)
    return crc ^ 0xffffffff


def _masked_crc(data: bytes) -> int:
    crc = _crc32c(data)
    return (((crc >> 15) | (crc << 17)) + 0xa282ead8) & 0xffffffff


def _log_records(data: bytes) -> Iterator[bytes]:
    offset, fragments = 0, None
    while offset < len(data):
        remaining = 32768 - offset % 32768
        if remaining < 7:
            offset += remaining
            continue
        if len(data) - offset < 7:
            return  # An incomplete final physical record has not committed.
        checksum, length, kind = struct.unpack_from("<IHB", data, offset)
        if checksum == length == kind == 0:
            offset += remaining
            continue
        if length > remaining - 7:
            raise LevelDBReadError("LevelDB record crosses a block boundary")
        start = offset + 7
        if start + length > len(data):
            return
        payload = data[start:start + length]
        offset = start + length
        if _masked_crc(bytes([kind]) + payload) != checksum:
            raise LevelDBReadError("LevelDB record checksum failed")
        if kind == 1:
            if fragments is not None:
                raise LevelDBReadError("unfinished LevelDB fragmented record")
            yield payload
        elif kind == 2:
            if fragments is not None:
                raise LevelDBReadError("overlapping LevelDB fragments")
            fragments = bytearray(payload)
        elif kind in (3, 4) and fragments is not None:
            fragments.extend(payload)
            if kind == 4:
                yield bytes(fragments)
                fragments = None
        else:
            raise LevelDBReadError("invalid LevelDB fragment type")


def _manifest(data: bytes) -> Tuple[set[int], int, int]:
    live, log_number, previous_log = set(), None, 0
    for record in _log_records(data):
        offset = 0
        while offset < len(record):
            tag, offset = _varint(record, offset)
            if tag == 1:
                _, offset = _slice(record, offset)
            elif tag in (2, 3, 4, 9):
                value, offset = _varint(record, offset)
                if tag == 2:
                    log_number = value
                elif tag == 9:
                    previous_log = value
            elif tag == 5:
                _, offset = _varint(record, offset)
                _, offset = _slice(record, offset)
            elif tag == 6:
                _, offset = _varint(record, offset)
                number, offset = _varint(record, offset)
                live.discard(number)
            elif tag == 7:
                _, offset = _varint(record, offset)
                number, offset = _varint(record, offset)
                _, offset = _varint(record, offset)
                _, offset = _slice(record, offset)
                _, offset = _slice(record, offset)
                live.add(number)
            else:
                raise LevelDBReadError("unsupported LevelDB manifest field")
    if log_number is None:
        raise LevelDBReadError("LevelDB manifest has no active log")
    return live, log_number, previous_log


def _batches(data: bytes) -> Iterator[Tuple[int, bytes, Optional[bytes]]]:
    for record in _log_records(data):
        if len(record) < 12:
            raise LevelDBReadError("truncated LevelDB write batch")
        sequence, count = struct.unpack_from("<QI", record)
        offset = 12
        for index in range(count):
            if offset >= len(record):
                raise LevelDBReadError("truncated LevelDB batch entry")
            tag = record[offset]
            offset += 1
            key, offset = _slice(record, offset)
            if tag == 1:
                value, offset = _slice(record, offset)
            elif tag == 0:
                value = None
            else:
                raise LevelDBReadError("unsupported LevelDB batch entry")
            yield sequence + index, key, value
        if offset != len(record):
            raise LevelDBReadError("unexpected LevelDB batch suffix")


def _snappy(data: bytes) -> bytes:
    expected, offset = _varint(data, 0)
    if expected > 64 * 1024 * 1024:
        raise LevelDBReadError("LevelDB block exceeds the reader limit")
    output = bytearray()
    while offset < len(data):
        tag = data[offset]
        offset += 1
        kind = tag & 3
        if kind == 0:
            length = tag >> 2
            if length < 60:
                length += 1
            else:
                size = length - 59
                if offset + size > len(data):
                    raise LevelDBReadError("truncated Snappy literal")
                length = int.from_bytes(data[offset:offset + size], "little") + 1
                offset += size
            if offset + length > len(data):
                raise LevelDBReadError("truncated Snappy literal")
            output.extend(data[offset:offset + length])
            offset += length
        else:
            size = 1 if kind == 1 else 2 if kind == 2 else 4
            if offset + size > len(data):
                raise LevelDBReadError("truncated Snappy copy")
            distance = int.from_bytes(data[offset:offset + size], "little")
            offset += size
            if kind == 1:
                distance |= (tag & 0xe0) << 3
                length = 4 + ((tag >> 2) & 7)
            else:
                length = 1 + (tag >> 2)
            if not distance or distance > len(output):
                raise LevelDBReadError("invalid Snappy copy distance")
            for _ in range(length):
                output.append(output[-distance])
        if len(output) > expected:
            raise LevelDBReadError("Snappy block size mismatch")
    if len(output) != expected:
        raise LevelDBReadError("Snappy block size mismatch")
    return bytes(output)


def _block(data: bytes, handle: bytes) -> bytes:
    offset, position = _varint(handle, 0)
    size, _ = _varint(handle, position)
    if offset + size + 5 > len(data):
        raise LevelDBReadError("LevelDB table block is out of range")
    compressed, kind = data[offset:offset + size], data[offset + size]
    checksum = struct.unpack_from("<I", data, offset + size + 1)[0]
    if _masked_crc(compressed + bytes([kind])) != checksum:
        raise LevelDBReadError("LevelDB table block checksum failed")
    if kind == 0:
        return compressed
    if kind == 1:
        return _snappy(compressed)
    raise LevelDBReadError("unsupported LevelDB table compression")


def _block_entries(data: bytes) -> Iterator[Tuple[bytes, bytes]]:
    if len(data) < 8:
        raise LevelDBReadError("invalid LevelDB block footer")
    count = struct.unpack_from("<I", data, len(data) - 4)[0]
    end = len(data) - 4 - count * 4
    if count < 1 or end < 0:
        raise LevelDBReadError("invalid LevelDB restart count")
    offset, previous = 0, b""
    while offset < end:
        shared, offset = _varint(data, offset)
        size, offset = _varint(data, offset)
        value_size, offset = _varint(data, offset)
        if shared > len(previous) or offset + size + value_size > end:
            raise LevelDBReadError("invalid LevelDB block entry")
        key = previous[:shared] + data[offset:offset + size]
        offset += size
        value = data[offset:offset + value_size]
        offset += value_size
        yield key, value
        previous = key
    if offset != end:
        raise LevelDBReadError("invalid LevelDB block boundary")


def _table(data: bytes) -> Iterator[Tuple[int, bytes, Optional[bytes]]]:
    if len(data) < 48 or data[-8:] != bytes.fromhex("57fb808b247547db"):
        raise LevelDBReadError("invalid LevelDB table magic")
    footer = data[-48:-8]
    _, offset = _varint(footer, 0)
    _, offset = _varint(footer, offset)
    # The remainder begins with the index block handle (offset and size).
    index = _block(data, footer[offset:])
    for _, handle in _block_entries(index):
        for internal, value in _block_entries(_block(data, handle)):
            if len(internal) < 8:
                raise LevelDBReadError("invalid LevelDB internal key")
            tag = struct.unpack_from("<Q", internal, len(internal) - 8)[0]
            kind, sequence = tag & 255, tag >> 8
            if kind not in (0, 1):
                raise LevelDBReadError("unsupported LevelDB value type")
            yield sequence, internal[:-8], value if kind else None


def _string(data: bytes) -> str:
    if not data:
        raise LevelDBReadError("empty Chromium string")
    if data[0] == 1:
        return data[1:].decode("latin1")
    if data[0] == 0:
        return data[1:].decode("utf-16-le")
    raise LevelDBReadError("unsupported Chromium string encoding")


def read_local_storage(directory: Path, origin: str, names: Sequence[str]) -> Dict[str, str]:
    """Return only requested current values for one exact, caller-pinned origin."""
    prefix = b"_" + origin.encode("utf-8") + b"\x00"
    wanted = set(names)
    last_error = None
    for _ in range(3):
        try:
            current = (directory / "CURRENT").read_bytes()
            manifest_name = current.decode("ascii").strip()
            if not re.fullmatch(r"MANIFEST-\d+", manifest_name):
                raise LevelDBReadError("invalid LevelDB CURRENT pointer")
            manifest = (directory / manifest_name).read_bytes()
            tables, minimum_log, previous_log = _manifest(manifest)
            paths = []
            for number in sorted(tables):
                candidates = [directory / ("%06d%s" % (number, suffix)) for suffix in (".ldb", ".sst")]
                table_path = next((path for path in candidates if path.is_file()), None)
                if table_path is None:
                    raise LevelDBReadError("active LevelDB table is unavailable")
                paths.append((table_path, _table))
            logs = [path for path in directory.iterdir() if re.fullmatch(r"\d+\.log", path.name) and (int(path.stem) >= minimum_log or int(path.stem) == previous_log)]
            paths.extend((path, _batches) for path in sorted(logs))
            if minimum_log and not any(int(path.stem) == minimum_log for path in logs):
                raise LevelDBReadError("active LevelDB log is unavailable")
            latest: Dict[str, Tuple[int, Optional[bytes]]] = {}
            fingerprints = []
            for path, reader in paths:
                before = path.stat()
                if before.st_size > 512 * 1024 * 1024:
                    raise LevelDBReadError("LevelDB file exceeds the reader limit")
                data = path.read_bytes()
                for sequence, key, value in reader(data):
                    if not key.startswith(prefix):
                        continue
                    name = _string(key[len(prefix):])
                    if name not in wanted:
                        continue
                    previous = latest.get(name)
                    if previous is None or sequence > previous[0]:
                        latest[name] = (sequence, value)
                    elif sequence == previous[0] and value != previous[1]:
                        raise LevelDBReadError("conflicting LevelDB sequence values")
                fingerprints.append((path, before.st_size, before.st_mtime_ns))
            if (directory / "CURRENT").read_bytes() != current or (directory / manifest_name).read_bytes() != manifest or any((path.stat().st_size, path.stat().st_mtime_ns) != (size, mtime) for path, size, mtime in fingerprints):
                raise LevelDBReadError("LevelDB snapshot changed while reading")
            return {name: _string(value) for name, (_, value) in latest.items() if value is not None}
        except (OSError, UnicodeError, ValueError, struct.error) as exc:
            last_error = exc
    raise LevelDBReadError("current Chromium local storage could not be read") from last_error
