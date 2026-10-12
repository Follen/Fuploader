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
import json
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
    "11509": {"gameVersion": "1.15.9", "server": "wow_classic_era"},
    "16001": {"gameVersion": "1.60.1", "server": "wow_forever"},
    "20506": {"gameVersion": "2.5.6", "server": "wow_anniversary"},
    "38002": {"gameVersion": "3.80.2", "server": "wow_classic_titan"},
    "40402": {"gameVersion": "4.4.2", "server": "wow_classic_cata"},
    "50504": {"gameVersion": "5.5.4", "server": "wow_classic"},
}

# Recognized WoW clients in universal ZIPs which currently have no Creator
# server mapping. Preserve their Interface codes, without inventing wire keys.
KNOWN_UNMAPPED_INTERFACES = {"30405"}

_INTERFACE_RE = re.compile(r"^\s*##\s*Interface\s*:\s*(.*?)\s*$", re.IGNORECASE)
_INTERFACE_VALUE_RE = re.compile(r"^\d+$")
_SOURCE = Union[str, os.PathLike[str], bytes, bytearray, memoryview, BinaryIO]


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

    Each addon's base and recognized flavor TOCs form one Interface union.
    Independent addons must declare the same union. This avoids
    choosing an arbitrary addon when a multi-addon archive contains
    incompatible game versions.  TOCs under a ``Libs`` directory are ignored.
    Multiple Interface values in one TOC are supported and become a
    deterministic comma-separated ``toc_version``.

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
    signatures: List[Tuple[str, Tuple[str, ...]]] = []
    for name, toc_raw in addon_entries:
        values = tuple(_interface_values(_decode_toc(toc_raw, name), name))
        signatures.append((name, values))
    groups: Dict[str, set[str]] = {}
    for name, values in signatures:
        normalized = name.replace("\\", "/").casefold()
        addon = re.sub(r"_(?:mainline|vanilla|classic|bcc|tbc|wrath|cata|mists)\.toc$", ".toc", normalized)
        groups.setdefault(addon, set()).update(values)
    first = next(iter(groups))
    expected = tuple(sorted(groups[first], key=lambda item: (int(item), item)))
    mismatches = [name for name, values in groups.items() if values != set(expected)]
    if mismatches:
        names = ", ".join([first, *mismatches])
        raise ValidationError("addon TOC Interface values are ambiguous across files: %s" % names, path="$.file")

    unknown = [value for value in expected
               if value not in INTERFACE_GAME_VERSION_MAP and value not in KNOWN_UNMAPPED_INTERFACES]
    if unknown:
        raise ValidationError(
            "unsupported addon TOC Interface value(s): %s" % ", ".join(unknown),
            path="$.file",
        )

    games: List[Dict[str, str]] = []
    for interface in expected:
        if interface in KNOWN_UNMAPPED_INTERFACES:
            continue
        candidate = dict(INTERFACE_GAME_VERSION_MAP[interface])
        if candidate not in games:
            games.append(candidate)
    return {
        "toc_version": ",".join(expected),
        "supported_game_versions": games,
        "interface_values": list(expected),
        "toc_files": [name for name, _ in signatures],
        "unmapped_interface_values": [value for value in expected if value in KNOWN_UNMAPPED_INTERFACES],
    }


# Short alias for integration code that already calls metadata parsers by a
# generic name.
parse_zip_metadata = parse_modus_zip


def select_game_versions(derived: Sequence[Mapping[str, str]], config: Any,
                         supplied: Any = None) -> List[Dict[str, str]]:
    """Default to exact TOC builds; allow explicit live builds on ZIP clients."""
    rows = config if isinstance(config, list) else []
    row = next((item for item in rows if isinstance(item, Mapping) and item.get("key") == "wow_builds"), None)
    try:
        builds = json.loads(row["value"]) if row and isinstance(row.get("value"), str) else None
    except (ValueError, TypeError):
        builds = None
    if not isinstance(builds, Mapping) or not builds or any(
        not isinstance(value, Mapping) or not isinstance(value.get("versions"), list)
        or any(not isinstance(version, str) or not version.strip() for version in value["versions"])
        for value in builds.values()
    ):
        raise ValidationError("live wow_builds config is missing or malformed", path="$.supported_game_versions")
    available = [dict(item) for item in derived
                 if item["server"] in builds and item["gameVersion"] in builds[item["server"]]["versions"]]
    # An explicit build is the author's compatibility declaration, like the
    # Creator dropdown. It must still belong to a client present in the ZIP
    # and be offered by the live service. Never opt into newer builds by default.
    clients = {item["server"] for item in derived}
    live_choices = [{"server": server, "gameVersion": version}
                    for server in builds if server in clients
                    for version in builds[server]["versions"]]
    selected = available if supplied is None else supplied
    if not isinstance(selected, list) or not selected or any(item not in live_choices for item in selected):
        raise ValidationError("supported_game_versions must be a nonempty subset of ZIP client branches and live Creator choices", path="$.supported_game_versions")
    if len({(item["server"], item["gameVersion"]) for item in selected}) != len(selected):
        raise ValidationError("supported_game_versions must not contain duplicates", path="$.supported_game_versions")
    return [dict(item) for item in selected]


__all__ = ["INTERFACE_GAME_VERSION_MAP", "parse_modus_zip", "parse_zip_metadata", "select_game_versions"]
