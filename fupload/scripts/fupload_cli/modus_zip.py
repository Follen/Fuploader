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


# Explicit Interface codes to ModUs game-version labels.  A numeric code is
# not enough to infer a new client, so unknown values fail.  The current
# dropdown (wow_builds) is retail 12.1.0, Mists 5.5.4, Era 1.15.9, Titan
# 3.80.2, and Anniversary 2.5.6.  Older retail and Era codes stay so
# previously parsed packages keep their labels.
INTERFACE_GAME_VERSION_MAP: Mapping[str, Mapping[str, str]] = {
    "110000": {"gameVersion": "11.0.0", "server": "wow_retail"},
    "110002": {"gameVersion": "11.0.2", "server": "wow_retail"},
    "111000": {"gameVersion": "11.1.0", "server": "wow_retail"},
    "111005": {"gameVersion": "11.1.5", "server": "wow_retail"},
    "120100": {"gameVersion": "12.1.0", "server": "wow_retail"},
    "11506": {"gameVersion": "Classic Era", "server": "wow_classic_era"},
    "11507": {"gameVersion": "Classic Era", "server": "wow_classic_era"},
    "11508": {"gameVersion": "Classic Era", "server": "wow_classic_era"},
    "11509": {"gameVersion": "1.15.9", "server": "wow_classic_era"},
    "20506": {"gameVersion": "2.5.6", "server": "wow_anniversary"},
    "38002": {"gameVersion": "3.80.2", "server": "wow_classic_titan"},
    "50504": {"gameVersion": "5.5.4", "server": "wow_classic"},
}

# Shipped TOC codes for clients the current ModUs dropdown does not offer.
# 40401/40402 are Cataclysm; 16001 is the forever/1.60.1 client.  They are
# omitted when a current client is also declared, and rejected when alone.
_UNLISTED_INTERFACE_CODES = frozenset({"40401", "40402", "16001"})
_FLAVOR_SUFFIXES = ("_mainline", "_vanilla", "_tbc", "_wrath", "_cata", "_mists")

_INTERFACE_RE = re.compile(r"^\s*##\s*Interface\s*:\s*(.*?)\s*$", re.IGNORECASE)
_INTERFACE_VALUE_RE = re.compile(r"^\d+$")
_SOURCE = Union[str, os.PathLike[str], bytes, bytearray, memoryview, BinaryIO]


def _is_flavor_toc(name: str) -> bool:
    """Return whether ``name`` is a client-specific WoW TOC.

    Files such as ``Addon_Mists.toc`` replace ``Addon.toc`` on that client.
    Their Interface values are a union.  The unsuffixed TOC is not consulted
    once any flavor TOC is present, so a fallback retail code cannot relabel
    a classic package.
    """
    stem = Path(name.replace("\\", "/")).stem.casefold()
    return stem.endswith(_FLAVOR_SUFFIXES)


def _is_library_toc(name: str) -> bool:
    """Return whether ``name`` is an embedded library TOC.

    Creator's release form reads the addon TOC.  Libraries such as Ace3 and
    LibDeflate live under a ``Libs`` directory and declare their own Interface
    values, so treating them as addons rejects packages the Creator accepts.
    """
    parts = name.replace("\\", "/").split("/")
    return any(part.casefold() == "libs" for part in parts[:-1])


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

    Addon ``.toc`` files must declare the same Interface set.  This avoids
    choosing an arbitrary addon when a multi-addon archive contains
    incompatible game versions.  Client flavor TOCs (``_Mists``, ``_Vanilla``
    and the other standard suffixes) are the exception: their Interface values
    are combined, and the unsuffixed TOC is ignored while any flavor TOC
    exists.  TOCs under a ``Libs`` directory are ignored.  Interface codes for
    clients absent from the current ModUs dropdown are omitted.  Multiple
    Interface values in one TOC are supported and become a deterministic
    comma-separated ``toc_version``.

    Returned keys are JSON-ready and use the exact snake_case names accepted
    by the Fupload ModUs schema.  ``interface_values`` and ``toc_files`` are
    diagnostic fields for callers and can be omitted from the wire request.
    """
    raw, source_name = _read_source(source)
    addon_entries = [
        (name, toc_raw)
        for name, toc_raw in _zip_entries(raw, source_name)
        if not _is_library_toc(name)
    ]
    if not addon_entries:
        raise ValidationError("ZIP contains no addon .toc file outside a Libs directory", path="$.file")
    flavor_entries = [(name, toc_raw) for name, toc_raw in addon_entries if _is_flavor_toc(name)]
    selected_entries = flavor_entries or addon_entries
    signatures: List[Tuple[str, Tuple[str, ...]]] = []
    for name, toc_raw in selected_entries:
        values = tuple(_interface_values(_decode_toc(toc_raw, name), name))
        signatures.append((name, values))
    if not flavor_entries:
        expected = signatures[0][1]
        mismatches = [name for name, values in signatures[1:] if values != expected]
        if mismatches:
            names = ", ".join([signatures[0][0], *mismatches])
            raise ValidationError("addon TOC Interface values are ambiguous across files: %s" % names, path="$.file")
        ordered = expected
    else:
        ordered = tuple(dict.fromkeys(value for _, values in signatures for value in values))
        ordered = tuple(sorted(ordered, key=lambda item: (int(item), item)))

    unknown = [value for value in ordered if value not in INTERFACE_GAME_VERSION_MAP and value not in _UNLISTED_INTERFACE_CODES]
    if unknown:
        raise ValidationError(
            "unsupported addon TOC Interface value(s): %s" % ", ".join(unknown),
            path="$.file",
        )
    expected = tuple(value for value in ordered if value in INTERFACE_GAME_VERSION_MAP)
    if not expected:
        raise ValidationError(
            "addon TOC Interface values are not offered by the current ModUs client list",
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
