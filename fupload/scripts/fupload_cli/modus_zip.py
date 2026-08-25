"""Derive ModUs release metadata from an addon ZIP archive.

The Creator release form sends two related values for a package:

* ``tocVersion`` is the Interface value(s) found in addon ``.toc`` files.
* ``supportedGameVersionsReqs`` contains ``{gameVersion, server}`` objects.

This module intentionally uses an explicit interface table.  A numeric
Interface value is not enough to safely infer a ModUs game choice when the
Creator adds a new client, so unknown values fail deterministically instead
of being silently classified.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, List, Mapping, Sequence, Tuple, Union

from .errors import ValidationError


# These are the game-version labels loaded by Creator's
# ReleaseFormPageViewModel.LoadDefaultGameVersions.  12.1.0 is also included
# because it is the live ModUs response used by the integration fixture.
# Classic values are the Interface values used by the corresponding WoW
# clients; all entries remain explicit so a new client cannot be guessed.
INTERFACE_GAME_VERSION_MAP: Mapping[str, Mapping[str, str]] = {
    "110000": {"gameVersion": "11.0.0", "server": "wow_retail"},
    "110002": {"gameVersion": "11.0.2", "server": "wow_retail"},
    "111000": {"gameVersion": "11.1.0", "server": "wow_retail"},
    "111005": {"gameVersion": "11.1.5", "server": "wow_retail"},
    "120100": {"gameVersion": "12.1.0", "server": "wow_retail"},
    "11506": {"gameVersion": "Classic Era", "server": "wow_classic_era"},
    "11507": {"gameVersion": "Classic Era", "server": "wow_classic_era"},
    "11508": {"gameVersion": "Classic Era", "server": "wow_classic_era"},
    "40401": {"gameVersion": "Cataclysm Classic", "server": "wow_classic_cata"},
    "40402": {"gameVersion": "Cataclysm Classic", "server": "wow_classic_cata"},
}

_INTERFACE_RE = re.compile(r"^\s*##\s*Interface\s*:\s*(.*?)\s*$", re.IGNORECASE)
_INTERFACE_VALUE_RE = re.compile(r"^\d+$")
_SOURCE = Union[str, os.PathLike[str], bytes, bytearray, memoryview, BinaryIO]


def _read_source(source: _SOURCE) -> Tuple[bytes, str]:
    """Read a path, byte buffer, or seekable stream without leaking content."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source), "<bytes>"
    if hasattr(source, "read"):
        try:
            data = source.read()  # type: ignore[union-attr]
        except OSError as exc:
            raise ValidationError("cannot read ZIP archive: %s" % exc, path="$.file") from exc
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValidationError("ZIP source must return bytes", path="$.file")
        return bytes(data), "<stream>"
    path = Path(source)
    if not path.is_file():
        raise ValidationError("file does not exist or is not a regular file", path="$.file")
    try:
        return path.read_bytes(), str(path)
    except OSError as exc:
        raise ValidationError("cannot read ZIP archive: %s" % exc, path="$.file") from exc


def _decode_toc(raw: bytes, name: str) -> str:
    # Creator-generated TOCs are UTF-8.  A small number of legacy addon TOCs
    # use Windows-1252, which is deterministic to support without guessing.
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ValidationError("addon TOC is not valid UTF-8 or Windows-1252", path="$.file:%s" % name) from exc


def _interface_values(text: str, name: str) -> List[str]:
    values: List[str] = []
    for line in text.splitlines():
        match = _INTERFACE_RE.match(line)
        if not match:
            continue
        value_text = match.group(1).strip()
        if not value_text:
            raise ValidationError("addon TOC Interface value is missing", path="$.file:%s" % name)
        candidates = [item for item in re.split(r"[;,\s]+", value_text) if item]
        if not candidates or any(not _INTERFACE_VALUE_RE.fullmatch(item) for item in candidates):
            raise ValidationError("addon TOC Interface value must contain decimal codes", path="$.file:%s" % name)
        values.extend(candidates)
    if not values:
        raise ValidationError("addon TOC has no Interface field", path="$.file:%s" % name)
    unique = list(dict.fromkeys(values))
    return sorted(unique, key=lambda item: (int(item), item))


def _zip_entries(raw: bytes, source_name: str) -> Iterable[Tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValidationError("file must be a valid ZIP archive", path="$.file") from exc
    with archive:
        seen: set[str] = set()
        toc_infos = []
        for info in archive.infolist():
            name = info.filename
            if info.is_dir() or name.endswith("/") or not name.lower().endswith(".toc"):
                continue
            normalized = name.replace("\\", "/").casefold()
            if normalized in seen:
                raise ValidationError("ZIP contains duplicate addon TOC paths", path="$.file:%s" % name)
            seen.add(normalized)
            toc_infos.append(info)
        if not toc_infos:
            raise ValidationError("ZIP contains no addon .toc file", path="$.file")
        for info in sorted(toc_infos, key=lambda item: item.filename.casefold()):
            try:
                yield info.filename, archive.read(info)
            except (KeyError, RuntimeError, OSError) as exc:
                raise ValidationError("cannot read addon TOC from ZIP", path="$.file:%s" % info.filename) from exc


def parse_modus_zip(source: _SOURCE) -> Dict[str, Any]:
    """Return ModUs metadata inferred from ``source``.

    Every ``.toc`` in the archive must declare the same Interface set.  This
    avoids choosing an arbitrary addon when a multi-addon archive contains
    incompatible game versions.  Multiple Interface values in one TOC are
    supported and become a deterministic comma-separated ``toc_version``.

    Returned keys are JSON-ready and use the exact snake_case names accepted
    by the Fupload ModUs schema.  ``interface_values`` and ``toc_files`` are
    diagnostic fields for callers and can be omitted from the wire request.
    """
    raw, source_name = _read_source(source)
    signatures: List[Tuple[str, Tuple[str, ...]]] = []
    for name, toc_raw in _zip_entries(raw, source_name):
        values = tuple(_interface_values(_decode_toc(toc_raw, name), name))
        signatures.append((name, values))
    expected = signatures[0][1]
    mismatches = [name for name, values in signatures[1:] if values != expected]
    if mismatches:
        names = ", ".join([signatures[0][0], *mismatches])
        raise ValidationError("addon TOC Interface values are ambiguous across files: %s" % names, path="$.file")

    unknown = [value for value in expected if value not in INTERFACE_GAME_VERSION_MAP]
    if unknown:
        raise ValidationError(
            "unsupported addon TOC Interface value(s): %s" % ", ".join(unknown),
            path="$.file",
        )

    games: List[Dict[str, str]] = []
    for interface in expected:
        candidate = dict(INTERFACE_GAME_VERSION_MAP[interface])
        if candidate not in games:
            games.append(candidate)
    return {
        "toc_version": ",".join(expected),
        "supported_game_versions": games,
        "interface_values": list(expected),
        "toc_files": [name for name, _ in signatures],
    }


# Short alias for integration code that already calls metadata parsers by a
# generic name.
parse_zip_metadata = parse_modus_zip


__all__ = ["INTERFACE_GAME_VERSION_MAP", "parse_modus_zip", "parse_zip_metadata"]
