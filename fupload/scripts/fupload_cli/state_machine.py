"""ModUs Creator project form state machine.

The desktop Creator exposes three form tabs in order: choose a game, enter
general project information, and select/build a license.  This module keeps
that sequencing explicit for CLI callers and provides a small JSON-safe
snapshot that can be resumed after an interrupted form submission.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from .errors import ValidationError


class ProjectStep(str, Enum):
    """Persisted steps exposed by the Creator form."""

    CHOOSE_GAME = "choose_game"
    SELECT_GAME = "choose_game"
    BASIC_INFO = "basic_info"
    GENERAL = "basic_info"
    LICENSE = "license"
    COMPLETE = "complete"


# String aliases make the state machine convenient for JSON/CLI consumers.
CHOOSE_GAME = ProjectStep.CHOOSE_GAME.value
SELECT_GAME = CHOOSE_GAME
BASIC_INFO = ProjectStep.BASIC_INFO.value
GENERAL = BASIC_INFO
LICENSE = ProjectStep.LICENSE.value
COMPLETE = ProjectStep.COMPLETE.value

_SCHEMA = "fupload.v1.modus.project-state"
_PLATFORMS = ("modus", "bigfoot")
_BIGFOOT_EXCLUSIVE_CATEGORY_ID = 998
_BASIC_INFO_KEYS = {
    # Shared create/edit form fields.
    "schema", "name", "project_name", "alt_name", "summary", "categories",
    "synchronization_type", "publish_platforms", "publishPlatforms",
    "required_tier_id", "requiredTierId", "repo_url",
    # Create-only image fields and edit-only detail/image fields.
    "logo_base64", "screenshot_base64s", "description",
    "required_dependencies", "images", "image_ops",
    # Known project-detail readback fields preserved in resumable snapshots.
    "cf_url", "logo", "status",
}
_LICENSE_KEYS = {
    "type", "template", "license_template", "licenseTemplate",
    "holder", "copyright_holder", "copyrightHolder",
    "year", "copyright_year", "copyrightYear",
    "content", "license_content", "licenseContent",
}


def _basic_info_fields(value: Mapping[str, Any]) -> None:
    unknown = sorted(set(value) - _BASIC_INFO_KEYS)
    if unknown:
        raise ValidationError(
            "unknown basic_info field(s): %s" % ", ".join(unknown),
            path="$.basic_info.%s" % unknown[0],
        )


def _nonempty_text(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("value must be a non-empty string", path=path)
    return value.strip()


def _required_tier(value: Any, *, path: str = "$.required_tier_id") -> Optional[int]:
    """Validate Creator's optional subscription-tier selection.

    ``None`` is the explicit "no required tier" branch.  The API contract
    uses a positive integer for a selected tier; booleans and numeric strings
    are rejected to avoid silently selecting the wrong dropdown item.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError("required_tier_id must be null or a positive integer", path=path)
    return value


def _platforms(value: Any, *, path: str = "$.publish_platforms") -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValidationError("publish_platforms must contain at least one platform", path=path)
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item not in _PLATFORMS:
            raise ValidationError("platform must be modus or bigfoot", path=f"{path}[{index}]")
        if item in result:
            raise ValidationError("publish_platforms must not contain duplicates", path=path)
        result.append(item)
    return result


def _categories(value: Any, *, path: str = "$.categories") -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValidationError("categories must contain at least one category ID", path=path)
    if len(value) > 5:
        raise ValidationError("categories must contain at most five category IDs", path=path)
    result: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValidationError("category ID must be a positive integer", path=f"{path}[{index}]")
        if item in result:
            raise ValidationError("categories must not contain duplicates", path=path)
        result.append(item)
    return result


def _game(value: Any) -> Any:
    """Require a game object/value that can be serialized and read back."""
    if isinstance(value, Mapping):
        if not value:
            raise ValidationError("game selection must not be empty", path="$.game")
        # Creator game entries have an ID/key and a display name.  Preserve
        # unknown fields for forward compatibility, but require one stable
        # identity field so a resumed snapshot remains addressable.
        identity = ("id", "gameId", "game_id", "key", "gameVersion", "game_version", "server")
        if not any(value.get(name) not in (None, "") for name in identity):
            raise ValidationError("game selection must include an identifier", path="$.game")
        return copy.deepcopy(dict(value))
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValidationError("game selection must be a non-empty object or string", path="$.game")


def _license(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        value = {"type": value}
    if not isinstance(value, Mapping):
        raise ValidationError("license must be a non-empty object or string", path="$.license")
    unknown = sorted(set(value) - _LICENSE_KEYS)
    if unknown:
        raise ValidationError("unknown license field(s): %s" % ", ".join(unknown), path="$.license.%s" % unknown[0])
    aliases = {
        "type": ("type", "template", "license_template", "licenseTemplate"),
        "holder": ("holder", "copyright_holder", "copyrightHolder"),
        "year": ("year", "copyright_year", "copyrightYear"),
        "content": ("content", "license_content", "licenseContent"),
    }
    result: Dict[str, Any] = {}
    for target, names in aliases.items():
        for name in names:
            if name in value and value[name] is not None:
                result[target] = value[name]
                break
    result["type"] = _nonempty_text(result.get("type"), path="$.license.type")
    for name in ("holder", "year", "content"):
        if name in result and result[name] is not None:
            result[name] = _nonempty_text(result[name], path="$.license.%s" % name)
    if result["type"].lower() in {"custom", "自定义"} and not result.get("content"):
        raise ValidationError("custom license content must not be empty", path="$.license.content")
    return result


class ProjectStateMachine:
    """Sequenced, resumable ModUs project creation/edit form."""

    schema = _SCHEMA

    def __init__(self, snapshot: Optional[Mapping[str, Any]] = None) -> None:
        self._step = ProjectStep.CHOOSE_GAME.value
        self._game: Any = None
        self._basic_info: Dict[str, Any] = {}
        self._license: Dict[str, Any] = {}
        if snapshot is not None:
            self._restore(snapshot)

    @property
    def state(self) -> str:
        return self._step

    @property
    def current_step(self) -> str:
        return self._step

    @property
    def game(self) -> Any:
        return copy.deepcopy(self._game)

    @property
    def basic_info(self) -> Dict[str, Any]:
        return copy.deepcopy(self._basic_info)

    @property
    def license(self) -> Dict[str, Any]:
        return copy.deepcopy(self._license)

    def _require(self, expected: ProjectStep) -> None:
        if self._step != expected.value:
            raise ValidationError(
                "project state %s cannot submit step %s"
                % (self._step, expected.value),
                path="$.state",
            )

    def select_game(self, game: Any) -> Dict[str, Any]:
        self._require(ProjectStep.CHOOSE_GAME)
        self._game = _game(game)
        self._step = ProjectStep.BASIC_INFO.value
        return self.snapshot()

    def submit_basic_info(self, info: Optional[Mapping[str, Any]] = None, **fields: Any) -> Dict[str, Any]:
        self._require(ProjectStep.BASIC_INFO)
        value: Dict[str, Any] = dict(info or {})
        value.update(fields)
        _basic_info_fields(value)
        name = value.get("name", value.get("project_name"))
        summary = value.get("summary")
        _nonempty_text(name, path="$.basic_info.name")
        _nonempty_text(summary, path="$.basic_info.summary")
        selected = value.get("publish_platforms", value.get("publishPlatforms"))
        value["publish_platforms"] = _platforms(selected, path="$.basic_info.publish_platforms")
        value.pop("publishPlatforms", None)
        value["categories"] = _categories(value.get("categories"), path="$.basic_info.categories")
        if _BIGFOOT_EXCLUSIVE_CATEGORY_ID in value["categories"] and value["publish_platforms"] != ["bigfoot"]:
            raise ValidationError(
                "category 998 requires bigfoot as the only publish platform",
                path="$.basic_info.publish_platforms",
            )
        if "required_tier_id" in value:
            value["required_tier_id"] = _required_tier(value["required_tier_id"], path="$.basic_info.required_tier_id")
        elif "requiredTierId" in value:
            value["required_tier_id"] = _required_tier(value.pop("requiredTierId"), path="$.basic_info.requiredTierId")
        else:
            # Explicitly persist the no-tier branch so reloads are stable.
            value["required_tier_id"] = None
        if "bigfoot" in value["publish_platforms"] and value["required_tier_id"] is not None:
            raise ValidationError(
                "required_tier_id must be null when bigfoot is selected",
                path="$.basic_info.required_tier_id",
            )
        derived_sync_type = (1 if "modus" in value["publish_platforms"] else 0) | (
            2 if "bigfoot" in value["publish_platforms"] else 0
        )
        # Creator exposes platform toggles, not synchronizationType itself.
        # Always replace a stale caller value with the UI-derived bit mask.
        value["synchronization_type"] = derived_sync_type
        if "project_name" in value:
            value["name"] = value.pop("project_name")
        self._basic_info = copy.deepcopy(value)
        self._step = ProjectStep.LICENSE.value
        return self.snapshot()

    def submit_license(self, license_value: Any = None, **fields: Any) -> Dict[str, Any]:
        self._require(ProjectStep.LICENSE)
        value: Any = license_value
        if value is None and fields:
            value = fields
        elif fields:
            if not isinstance(value, Mapping):
                raise ValidationError("license fields require an object", path="$.license")
            merged = dict(value)
            merged.update(fields)
            value = merged
        self._license = _license(value)
        self._step = ProjectStep.COMPLETE.value
        return self.snapshot()

    # Friendly aliases used by form adapters that name the first tab
    # "select game" and the second tab "general".
    choose_game = select_game
    set_game = select_game
    set_basic_info = submit_basic_info
    set_license = submit_license

    def submit(self, step: str, payload: Any = None, **fields: Any) -> Dict[str, Any]:
        """Dispatch a named step for generic CLI adapters."""
        normalized = str(step).strip().lower().replace("-", "_")
        if normalized in {"choose_game", "game"}:
            return self.select_game(payload)
        if normalized in {"basic_info", "general", "basic"}:
            return self.submit_basic_info(payload, **fields)
        if normalized == "license":
            return self.submit_license(payload, **fields)
        raise ValidationError("unsupported project state step", path="$.state")

    def snapshot(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "state": self._step,
            "game": copy.deepcopy(self._game),
            "basic_info": copy.deepcopy(self._basic_info),
            "license": copy.deepcopy(self._license),
        }

    to_dict = snapshot

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "ProjectStateMachine":
        return cls(snapshot)

    def _restore(self, snapshot: Mapping[str, Any]) -> None:
        if not isinstance(snapshot, Mapping) or snapshot.get("schema") != self.schema:
            raise ValidationError("invalid project state snapshot", path="$.schema")
        state = snapshot.get("state")
        if state not in {item.value for item in ProjectStep}:
            raise ValidationError("invalid project state", path="$.state")
        game = snapshot.get("game")
        basic = snapshot.get("basic_info") or {}
        lic = snapshot.get("license") or {}
        restored_game: Any = None
        restored_basic: Dict[str, Any] = {}
        restored_license: Dict[str, Any] = {}
        if state != CHOOSE_GAME:
            restored_game = _game(game)
        if state in {LICENSE, COMPLETE}:
            if not isinstance(basic, Mapping):
                raise ValidationError("basic_info must be an object", path="$.basic_info")
            restored_basic = dict(basic)
            _basic_info_fields(restored_basic)
            _nonempty_text(restored_basic.get("name"), path="$.basic_info.name")
            _nonempty_text(restored_basic.get("summary"), path="$.basic_info.summary")
            restored_basic["publish_platforms"] = _platforms(restored_basic.get("publish_platforms"))
            restored_basic["categories"] = _categories(restored_basic.get("categories"))
            restored_basic["required_tier_id"] = _required_tier(restored_basic.get("required_tier_id"))
            if _BIGFOOT_EXCLUSIVE_CATEGORY_ID in restored_basic["categories"] and restored_basic["publish_platforms"] != ["bigfoot"]:
                raise ValidationError("category 998 requires bigfoot as the only publish platform", path="$.basic_info.publish_platforms")
            if "bigfoot" in restored_basic["publish_platforms"] and restored_basic["required_tier_id"] is not None:
                raise ValidationError("required_tier_id must be null when bigfoot is selected", path="$.basic_info.required_tier_id")
            derived_sync_type = (1 if "modus" in restored_basic["publish_platforms"] else 0) | (2 if "bigfoot" in restored_basic["publish_platforms"] else 0)
            if restored_basic.get("synchronization_type") != derived_sync_type:
                raise ValidationError("synchronization_type must match publish_platforms", path="$.basic_info.synchronization_type")
        if state == COMPLETE:
            restored_license = _license(lic)
        self._game = restored_game
        self._basic_info = restored_basic
        self._license = restored_license
        self._step = str(state)

    def save(self, path: Union[str, os.PathLike[str]]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.snapshot(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    @classmethod
    def load(cls, path: Union[str, os.PathLike[str]]) -> "ProjectStateMachine":
        target = Path(path)
        try:
            with target.open("r", encoding="utf-8") as handle:
                snapshot = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ValidationError("project state snapshot could not be read", path=str(target)) from exc
        return cls.from_snapshot(snapshot)

    save_state = save
    load_state = load


__all__ = [
    "ProjectStep", "ProjectStateMachine", "CHOOSE_GAME", "SELECT_GAME",
    "BASIC_INFO", "GENERAL", "LICENSE", "COMPLETE",
]
