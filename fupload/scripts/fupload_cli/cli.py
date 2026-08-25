"""Argparse command tree for Fupload."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from . import __version__
from .dd import DD
from .curseforge import CurseForge
from .blackbox import Blackbox
from .errors import FuploadError, ValidationError
from .io import read_json, write_error, write_output
from .newbee import NewBee
from .schema import get_schema, schema_help


WRITE_HELP = """This command performs one remote business action from a versioned JSON document.

It is non-interactive. Unknown fields and fields belonging to another action are rejected.
On edit/update, an omitted field preserves the remote value; an explicit empty value clears it
only when the field contract permits. The provider GETs current detail and dynamic options before
building an allowlisted wire payload, then reads the result back after the write.

Public/review changes are never implicit. Set public and submit_for_review explicitly where the
schema exposes them. The calling Skill must show the complete plan and obtain confirmation first.
"""


def _modus_provider(*, authenticate: bool = True) -> Any:
    # Keep ModUs optional at import time so existing platform commands remain
    # usable while the provider is installed or upgraded independently.
    from .modus import Modus
    return Modus(authenticate=authenticate)


def _parser(**kwargs: Any) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        **kwargs,
    )


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _page_flags(parser: argparse.ArgumentParser, *, offset: bool = False) -> None:
    if offset:
        parser.add_argument("--offset", type=int, default=0, help="Zero-based result offset (technical default: 0).")
    else:
        parser.add_argument("--page", type=_positive, default=1, help="One-based page number (technical default: 1).")
    parser.add_argument("--page-size", type=_positive, default=50, help="Page size, capped by the platform (technical default: 50).")


def _list_flags(parser: argparse.ArgumentParser, *, offset: bool = False, game_type: bool = False) -> None:
    parser.add_argument("--keyword", default="", help="Optional name/title filter; empty means all current-author records.")
    _page_flags(parser, offset=offset)
    if game_type:
        parser.add_argument("--game-type", type=_positive, required=True, help="DD game type selected from `dd options game-types`.")


def _write_leaf(parent: argparse._SubParsersAction, platform: str, resource: str, action: str, summary: str, *, command: Optional[str] = None) -> None:
    command = command or action
    leaf = parent.add_parser(
        command, help=summary, description=summary + "\n\n" + WRITE_HELP,
        epilog=schema_help(platform, resource, action),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    leaf.add_argument("--input", required=True, metavar="PATH|-", help="Versioned JSON file, or - to read one JSON object from stdin.")
    leaf.add_argument("--dry-run", action="store_true", help="Validate schema and local files only; do not authenticate, upload, or write remotely.")
    if platform == "dd":
        leaf.add_argument("--session", help="Opaque task session ID returned by `dd session start`; required for a live DD operation.")
    leaf.set_defaults(handler="write", platform=platform, resource=resource, action=action)


def _read_leaf(parent: argparse._SubParsersAction, name: str, summary: str, **defaults: Any) -> argparse.ArgumentParser:
    leaf = parent.add_parser(name, help=summary, description=summary + "\n\nThis is a read-only command and emits stable JSON.")
    leaf.set_defaults(handler="read", **defaults)
    if defaults.get("platform") == "dd" and defaults.get("resource") != "session":
        leaf.add_argument("--session", help="Opaque task session ID returned by `dd session start`; required for this live DD read.")
    return leaf


def _newbee_relationship_tree(parent: argparse.ArgumentParser, resource: str, label: str) -> None:
    authors = parent.add_parser("co-author", help="Search, list, or replace %s co-authors" % label).add_subparsers(dest="author_action", required=True)
    leaf = _read_leaf(authors, "search", "Search current co-author candidates.", platform="newbee", resource=resource, action="co-author-search"); leaf.add_argument("--keyword", required=True)
    leaf = _read_leaf(authors, "list", "List current co-authors for one %s." % label, platform="newbee", resource=resource, action="co-author-list"); leaf.add_argument("--id", type=_positive, required=True)
    _write_leaf(authors, "newbee", resource + "-co-author", "set", "Replace the complete %s co-author list; an empty array clears it." % label)
    references = parent.add_parser("reference", help="Search, list, or replace %s content references" % label).add_subparsers(dest="reference_action", required=True)
    leaf = _read_leaf(references, "search", "Search content that can be referenced by this %s." % label, platform="newbee", resource=resource, action="reference-search"); leaf.add_argument("--keyword", required=True)
    leaf = _read_leaf(references, "list", "List current references for one %s." % label, platform="newbee", resource=resource, action="reference-list"); leaf.add_argument("--id", type=_positive, required=True)
    _write_leaf(references, "newbee", resource + "-reference", "set", "Replace the complete %s reference list; an empty array clears it." % label)


def _newbee_tree(platforms: argparse._SubParsersAction) -> None:
    root = platforms.add_parser("newbee", help="NewBeeBox Creator operations", description="Reuse the signed-in NewBeeBox desktop auth-store; no token input is accepted.")
    groups = root.add_subparsers(dest="resource_command", required=True)

    session = groups.add_parser("session", help="Authentication diagnostics").add_subparsers(dest="action_command", required=True)
    _read_leaf(session, "doctor", "Verify Windows Known Folder credentials, fixed official origins, and the Creator token exchange.", platform="newbee", resource="session", action="doctor")
    options = groups.add_parser("options", help="Read dynamic business choices before writing").add_subparsers(dest="option_action", required=True)
    for action, text in (
        ("content-origins", "List current content-origin values."),
        ("subscribe-plans", "List current author subscription plan levels."),
        ("time-ranges", "List current one-time purchase durations."),
    ):
        _read_leaf(options, action, text, platform="newbee", resource="options", action=action)

    plugin = groups.add_parser("plugin", help="Plugin create, version update, metadata edit, and reads").add_subparsers(dest="action_command", required=True)
    for action, text in (("create", "Create a private plugin record; public review is applied only after a version exists."), ("update", "Upload one immutable plugin version."), ("edit", "Edit plugin metadata or explicit public/review state."), ("delete", "Delete one explicitly confirmed plugin record.")):
        _write_leaf(plugin, "newbee", "plugin", action, text)
    leaf = _read_leaf(plugin, "list", "List plugins owned by the current author.", platform="newbee", resource="plugin", action="list"); _list_flags(leaf)
    leaf = _read_leaf(plugin, "get", "Read one plugin detail by numeric Creator ID.", platform="newbee", resource="plugin", action="get"); leaf.add_argument("--id", type=_positive, required=True)
    _read_leaf(plugin, "categories", "List current plugin categories and IDs.", platform="newbee", resource="plugin", action="categories")
    _read_leaf(plugin, "game-versions", "List current game branches/build IDs, including retail and classic variants.", platform="newbee", resource="plugin", action="game-versions")
    leaf = _read_leaf(plugin, "versions", "List uploaded versions for one plugin.", platform="newbee", resource="plugin", action="versions"); leaf.add_argument("--id", type=_positive, required=True); _page_flags(leaf)
    changelog = plugin.add_parser("changelog", help="Read or edit plugin version logs").add_subparsers(dest="changelog_action", required=True)
    leaf = _read_leaf(changelog, "list", "List version log records for one plugin.", platform="newbee", resource="plugin", action="changelog-list"); leaf.add_argument("--id", type=_positive, required=True); _page_flags(leaf)
    leaf = _read_leaf(changelog, "get", "Read one plugin version log by file ID.", platform="newbee", resource="plugin", action="changelog-get"); leaf.add_argument("--id", type=_positive, required=True)
    _write_leaf(changelog, "newbee", "plugin-changelog", "edit", "Edit or explicitly clear one existing plugin version log.")
    _newbee_relationship_tree(plugin, "plugin", "plugin")

    config = groups.add_parser("config", help="Configuration share create, backup update, metadata edit, and reads").add_subparsers(dest="action_command", required=True)
    for action, text in (("create", "Create a configuration share from an existing desktop cloud backup."), ("update", "Replace cloud-backup content selections without changing metadata."), ("edit", "Edit configuration metadata, business settings, channel, or review state."), ("delete", "Delete one explicitly confirmed configuration record.")):
        _write_leaf(config, "newbee", "config", action, text)
    leaf = _read_leaf(config, "list", "List configuration shares owned by the current author.", platform="newbee", resource="config", action="list"); _list_flags(leaf, offset=True)
    leaf = _read_leaf(config, "get", "Read a safe configuration-share detail without raw backup paths.", platform="newbee", resource="config", action="get"); leaf.add_argument("--id", type=_positive, required=True)
    _read_leaf(config, "backups", "List cloud backups already uploaded by the NewBeeBox desktop client.", platform="newbee", resource="config", action="backups")
    leaf = _read_leaf(config, "backup-get", "Read selectable plugins, ignored items, fonts, materials, and roles from one cloud backup.", platform="newbee", resource="config", action="backup-get"); leaf.add_argument("--id", type=_positive, required=True, help="Cloud backup ID.")
    _newbee_relationship_tree(config, "config", "configuration share")

    wa = groups.add_parser("wa", help="WA/string create, version update, metadata edit, and attached operations").add_subparsers(dest="action_command", required=True)
    for action, text in (("create", "Create a WA/string record and first string version."), ("update", "Publish one new immutable WA/string version."), ("edit", "Edit WA metadata, media, categories, attachments, business settings, or review state."), ("delete", "Delete one explicitly confirmed WA/string record.")):
        _write_leaf(wa, "newbee", "wa", action, text)
    leaf = _read_leaf(wa, "list", "List WA/string records owned by the current author; raw strings are redacted.", platform="newbee", resource="wa", action="list"); _list_flags(leaf, offset=True)
    leaf = _read_leaf(wa, "get", "Read one WA metadata detail; raw strings are replaced with length and SHA-256.", platform="newbee", resource="wa", action="get"); leaf.add_argument("--id", type=_positive, required=True)
    leaf = _read_leaf(wa, "categories", "List WA categories for a selected game version.", platform="newbee", resource="wa", action="categories"); leaf.add_argument("--game-version-id", type=_positive, required=True)
    _read_leaf(wa, "attachment-paths", "List platform-provided attachment install types and paths.", platform="newbee", resource="wa", action="attachment-paths")
    media = wa.add_parser("media", help="Upload one WA image or verified attachment material").add_subparsers(dest="media_action", required=True)
    _write_leaf(media, "newbee", "wa-media", "upload", "Upload one WA media file and return its reusable platform reference.")
    logs = wa.add_parser("changelog", help="Read or edit WA version logs").add_subparsers(dest="log_action", required=True)
    leaf = _read_leaf(logs, "latest", "Read the latest WA version summary.", platform="newbee", resource="wa", action="changelog-latest"); leaf.add_argument("--id", type=_positive, required=True)
    leaf = _read_leaf(logs, "list", "List WA version log records.", platform="newbee", resource="wa", action="changelog-list"); leaf.add_argument("--id", type=_positive, required=True); _page_flags(leaf)
    _write_leaf(logs, "newbee", "wa-changelog", "edit", "Edit or explicitly clear one WA version log.")
    _newbee_relationship_tree(wa, "wa", "WA")
    share_code = wa.add_parser("share-code", help="Set or refresh the NewBeeBox WA share code").add_subparsers(dest="share_code_action", required=True)
    _write_leaf(share_code, "newbee", "wa-share-code", "set", "Set or refresh the share code for one WA module.")


def _dd_tree(platforms: argparse._SubParsersAction) -> None:
    root = platforms.add_parser("dd", help="NetEase DD author operations", description="Use DD's official netease_dd.exe, credentials, native login, and NEP signer. No token input is accepted.")
    groups = root.add_subparsers(dest="resource_command", required=True)
    session = groups.add_parser("session", help="Installation and task-session lifecycle").add_subparsers(dest="action_command", required=True)
    _read_leaf(session, "doctor", "Discover DD, verify its official Authenticode publisher, and diagnose GUI/broker state without logging in.", platform="dd", resource="session", action="doctor")
    leaf = _read_leaf(session, "start", "Close confirmed official DD GUI instances, then start one task-scoped native login session.", platform="dd", resource="session", action="start")
    leaf.add_argument("--confirm-close-gui", action="store_true", help="Required only when doctor reports a running official DD GUI; the Skill obtains user consent before using it.")
    leaf = _read_leaf(session, "status", "Read the local task-broker status without creating a login.", platform="dd", resource="session", action="status")
    leaf.add_argument("--session", help="Optional opaque session ID; omitted selects the single active local session.")
    leaf = _read_leaf(session, "stop", "Log out and stop one DD task session.", platform="dd", resource="session", action="stop")
    leaf.add_argument("--session", required=True, help="Opaque session ID returned by `dd session start`.")
    options = groups.add_parser("options", help="Read dynamic business choices before writing").add_subparsers(dest="option_action", required=True)
    for action, text in (("game-types", "List DD game types."), ("channels", "List selectable DD rooms/channels for room association."), ("life-types", "List share-code and purchase life types."), ("vip-levels", "List available anchor VIP levels."), ("associated-acts", "List current-author content eligible for association.")):
        leaf = _read_leaf(options, action, text, platform="dd", resource="options", action=action)
        if action == "associated-acts":
            leaf.add_argument("--game-type", type=_positive, required=True)

    plugin = groups.add_parser("plugin", help="DD plugin create, version update, metadata edit, and reads").add_subparsers(dest="action_command", required=True)
    for action, text in (("create", "Create a DD plugin with its first selected version."), ("update", "Publish a DD plugin version while preserving first-publication metadata."), ("edit", "Edit DD plugin commercial, association, room/channel, and creation-statement settings."), ("delete", "Delete one explicitly confirmed DD plugin record.")):
        _write_leaf(plugin, "dd", "plugin", action, text)
    leaf = _read_leaf(plugin, "list", "List plugins owned by the current DD author account.", platform="dd", resource="plugin", action="list"); _list_flags(leaf, game_type=True)
    leaf = _read_leaf(plugin, "get", "Read one DD plugin detail by share SN.", platform="dd", resource="plugin", action="get"); leaf.add_argument("--sn", required=True)
    _read_leaf(plugin, "categories", "List DD plugin category choices.", platform="dd", resource="plugin", action="categories")
    leaf = _read_leaf(plugin, "game-versions", "List build choices for one DD game type.", platform="dd", resource="plugin", action="game-versions"); leaf.add_argument("--game-type", type=_positive, required=True)
    leaf = _read_leaf(plugin, "versions", "List versions for one DD plugin.", platform="dd", resource="plugin", action="versions"); leaf.add_argument("--sn", required=True); leaf.add_argument("--game-type", type=_positive, required=True); leaf.add_argument("--page", type=_positive, default=1)

    config = groups.add_parser("config", help="DD configuration create, backup-content update, metadata edit, and reads").add_subparsers(dest="action_command", required=True)
    for action, text in (("create", "Create a DD configuration share from an existing DD cloud backup."), ("update", "Update selected backup content and inner versions."), ("edit", "Edit DD configuration metadata and commercial/association settings."), ("delete", "Delete one explicitly confirmed DD configuration record.")):
        _write_leaf(config, "dd", "config", action, text)
    leaf = _read_leaf(config, "list", "List configuration shares owned by the current DD author.", platform="dd", resource="config", action="list"); _list_flags(leaf, game_type=True)
    leaf = _read_leaf(config, "get", "Read one DD configuration detail by share SN.", platform="dd", resource="config", action="get"); leaf.add_argument("--sn", required=True)
    _read_leaf(config, "backups", "List DD cloud backups available to the current account.", platform="dd", resource="config", action="backups")
    leaf = _read_leaf(config, "backup-get", "Read one DD backup's complete selectable content.", platform="dd", resource="config", action="backup-get"); leaf.add_argument("--sn", required=True)

    wa = groups.add_parser("wa", help="DD WA/string create, content update, metadata edit, and reads").add_subparsers(dest="action_command", required=True)
    for action, text in (("create", "Create a DD WA/string record."), ("update", "Publish updated DD WA content/version/material while preserving metadata."), ("edit", "Edit DD WA metadata and commercial/association settings."), ("delete", "Delete one explicitly confirmed DD WA/string record.")):
        _write_leaf(wa, "dd", "wa", action, text)
    leaf = _read_leaf(wa, "list", "List WA/string records owned by the current DD author.", platform="dd", resource="wa", action="list"); _list_flags(leaf, game_type=True)
    leaf = _read_leaf(wa, "get", "Read one DD WA detail by share SN.", platform="dd", resource="wa", action="get"); leaf.add_argument("--sn", required=True)
    leaf = _read_leaf(wa, "categories", "List DD WA category choices for a game type.", platform="dd", resource="wa", action="categories"); leaf.add_argument("--game-type", type=_positive, required=True)


def _curseforge_tree(platforms: argparse._SubParsersAction) -> None:
    root = platforms.add_parser("curseforge", help="CurseForge public project lookup and author uploads")
    groups = root.add_subparsers(dest="resource_command", required=True)
    session = groups.add_parser("session", help="Configuration diagnostics").add_subparsers(dest="action_command", required=True)
    _read_leaf(session, "doctor", "Check whether the fixed CurseForge configuration fields exist without revealing their values.", platform="curseforge", resource="session", action="doctor")
    project = groups.add_parser("project", help="Public project lookup").add_subparsers(dest="action_command", required=True)
    leaf = _read_leaf(project, "list", "List public WoW projects for one CurseForge author ID.", platform="curseforge", resource="project", action="list")
    leaf.add_argument("--author-id", type=_positive, help="Override CURSEFORGE_AUTHOR_ID for this lookup.")
    plugin = groups.add_parser("plugin", help="WoW plugin versions and uploads").add_subparsers(dest="action_command", required=True)
    _read_leaf(plugin, "game-versions", "List CurseForge Upload API game-version choices.", platform="curseforge", resource="plugin", action="game-versions")
    _write_leaf(plugin, "curseforge", "plugin", "upload", "Upload one plugin archive to an existing CurseForge project.")


def _blackbox_tree(platforms: argparse._SubParsersAction) -> None:
    root = platforms.add_parser(
        "blackbox",
        help="Heybox Workshop plugin management",
        description="Use a managed Heybox Workshop web session; an interactive browser opens when login is required.",
    )
    groups = root.add_subparsers(dest="resource_command", required=True)
    plugin = groups.add_parser("plugin", help="Heybox Workshop plugin metadata and versions").add_subparsers(dest="action_command", required=True)
    _read_leaf(plugin, "list", "List plugins managed by the current Heybox Workshop account.", platform="blackbox", resource="plugin", action="list")
    leaf = _read_leaf(plugin, "get", "Read one Heybox Workshop plugin and its versions.", platform="blackbox", resource="plugin", action="get")
    leaf.add_argument("--module-id", type=_positive, required=True)
    leaf = _read_leaf(plugin, "versions", "List versions for one Heybox Workshop plugin.", platform="blackbox", resource="plugin", action="versions")
    leaf.add_argument("--module-id", type=_positive, required=True)
    _write_leaf(plugin, "blackbox", "plugin", "edit", "Edit Heybox Workshop plugin metadata and verify the module readback.")
    _write_leaf(plugin, "blackbox", "plugin", "update", "Upload a ZIP and create a new Heybox Workshop plugin version.")
    _write_leaf(plugin, "blackbox", "version", "edit", "Edit an existing Heybox Workshop plugin version and verify its readback.", command="version-edit")
    _write_leaf(plugin, "blackbox", "version", "delete", "Soft-delete one Heybox Workshop plugin version and verify its deleted state.", command="version-delete")


def _modus_tree(platforms: argparse._SubParsersAction) -> None:
    root = platforms.add_parser(
        "modus", help="ModUs.Creator author plugin operations",
        description="Reuse the local ModUs.Creator Windows login state; token and signed upload material are never accepted as input.",
    )
    groups = root.add_subparsers(dest="resource_command", required=True)
    session = groups.add_parser("session", help="Local authentication diagnostics").add_subparsers(dest="action_command", required=True)
    _read_leaf(session, "doctor", "Check the local ModUs.Creator token store, DPAPI decryption, and authenticated API readiness without exposing credentials.", platform="modus", resource="session", action="doctor")

    account = groups.add_parser("account", help="ModUs author account and statistics").add_subparsers(dest="action_command", required=True)
    _read_leaf(account, "info", "Read the current ModUs account capability flags.", platform="modus", resource="account", action="info")
    _read_leaf(account, "subscription-count", "Read the active author subscription count.", platform="modus", resource="account", action="subscription-count")
    _read_leaf(account, "statistics", "Read current author project statistics.", platform="modus", resource="account", action="statistics")

    addon = groups.add_parser("addon", help="ModUs addon discovery and history APIs").add_subparsers(dest="action_command", required=True)
    leaf = _read_leaf(addon, "info", "Resolve addon directories to project records.", platform="modus", resource="addon", action="info")
    leaf.add_argument("--directory", dest="directories", action="append", required=True)
    leaf.add_argument("--server-type", type=int, default=1)
    leaf = _read_leaf(addon, "project-info", "Resolve addon project IDs to names.", platform="modus", resource="addon", action="project-info")
    leaf.add_argument("--project-id", dest="project_ids", action="append", type=_positive, required=True)
    leaf.add_argument("--server-type", type=int, default=1)
    leaf = _read_leaf(addon, "history", "Read addon project version history.", platform="modus", resource="addon", action="history")
    leaf.add_argument("--project-id", type=_positive, required=True)
    leaf.add_argument("--server-type", type=int, default=1)
    _page_flags(leaf)

    options = groups.add_parser("options", help="Read ModUs dynamic choices").add_subparsers(dest="option_action", required=True)
    _read_leaf(options, "categories", "List plugin categories returned by ModUs.", platform="modus", resource="options", action="categories")
    game_versions = _read_leaf(options, "game-versions", "List supported ModUs game versions.", platform="modus", resource="options", action="game-versions")
    game_versions.add_argument("--key", dest="keys", action="append", required=True, help="Request one game config key; repeatable.")
    _read_leaf(options, "subscription-tiers", "List author subscription tiers returned by ModUs.", platform="modus", resource="options", action="subscription-tiers")

    project = groups.add_parser("project", help="ModUs plugin project records").add_subparsers(dest="action_command", required=True)
    for action, text in (
        ("create", "Create a ModUs plugin project."),
        ("edit", "Edit ModUs plugin project metadata."),
        ("delete", "Delete one explicitly confirmed ModUs plugin project."),
    ):
        _write_leaf(project, "modus", "project", action, text)
    leaf = _read_leaf(project, "list", "List plugin projects owned by the current ModUs author.", platform="modus", resource="project", action="list"); _list_flags(leaf)
    leaf = _read_leaf(project, "get", "Read one ModUs plugin project detail.", platform="modus", resource="project", action="get"); leaf.add_argument("--project-id", type=_positive, required=True)
    leaf = _read_leaf(project, "dependencies", "Query ModUs project dependency candidates.", platform="modus", resource="project", action="dependencies")
    leaf.add_argument("--query", help="Dependency search text or JSON request body.")
    leaf.add_argument("--project-id", type=_positive)

    plugin = groups.add_parser("plugin", help="ModUs plugin releases and ZIP uploads").add_subparsers(dest="action_command", required=True)
    for action, text in (
        ("create", "Create and upload the first ModUs plugin release."),
        ("upload", "Upload a ModUs plugin ZIP and register its release metadata."),
        ("update", "Publish a new ModUs plugin release version."),
        ("edit", "Edit ModUs plugin release metadata."),
        ("delete", "Delete one explicitly confirmed ModUs plugin release."),
    ):
        _write_leaf(plugin, "modus", "plugin", action, text)
    leaf = _read_leaf(plugin, "list", "List releases for one ModUs plugin project.", platform="modus", resource="plugin", action="list"); leaf.add_argument("--project-id", type=_positive, required=True); _page_flags(leaf)
    leaf = _read_leaf(plugin, "get", "Read one ModUs plugin release detail.", platform="modus", resource="plugin", action="get"); leaf.add_argument("--project-id", type=_positive, required=True); leaf.add_argument("--file-id", type=_positive, required=True)
    leaf = _read_leaf(plugin, "versions", "List releases for one ModUs plugin project.", platform="modus", resource="plugin", action="versions"); leaf.add_argument("--project-id", type=_positive, required=True); _page_flags(leaf)


def build_parser() -> argparse.ArgumentParser:
    parser = _parser(
        prog="fupload",
        description="Atomic World of Warcraft author publishing CLI for NewBeeBox, NetEase DD, and CurseForge.",
        epilog="All output is JSON. Write commands require versioned JSON through --input and never prompt.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    platforms = parser.add_subparsers(dest="platform_command", required=True)
    _newbee_tree(platforms)
    _dd_tree(platforms)
    _curseforge_tree(platforms)
    _blackbox_tree(platforms)
    _modus_tree(platforms)
    return parser


def _validate_nested_files(doc: Dict[str, Any]) -> None:
    for name in ("screenshot_files", "picture_files", "image_files", "detail_img_files", "display_img_files"):
        if name not in doc:
            continue
        if not isinstance(doc[name], list):
            raise ValidationError("expected array", path="$.%s" % name)
        for index, value in enumerate(doc[name]):
            if not isinstance(value, str) or not os.path.isfile(value):
                raise ValidationError("file does not exist or is not a regular file", path="$.%s[%d]" % (name, index))


def _dry_run_data(doc: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    files = {}
    for name, value in doc.items():
        if name == "file" or name.endswith("_file"):
            if isinstance(value, str) and value:
                files[name] = {"name": Path(value).name, "size": Path(value).stat().st_size}
        elif name.endswith("_files") and isinstance(value, list):
            files[name] = [{"name": Path(path).name, "size": Path(path).stat().st_size} for path in value]
    return {
        "schema_valid": True,
        "input_schema": schema_name,
        "present_fields": sorted(set(doc) - {"schema"}),
        "local_files": files,
        "remote_validation_performed": False,
        "note": "Remote IDs, permissions, current state, and dynamic choices are checked only during execution.",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    platform = getattr(args, "platform", getattr(args, "platform_command", "unknown"))
    resource = getattr(args, "resource", "unknown")
    action = getattr(args, "action", "unknown")
    operation = "%s.%s" % (resource, action)
    try:
        if args.handler == "write":
            schema = get_schema(platform, resource, action)
            doc = schema.validate(read_json(args.input))
            _validate_nested_files(doc)
            if args.dry_run:
                write_output(platform, operation, _dry_run_data(doc, schema.name), dry_run=True)
                return 0
            provider = NewBee() if platform == "newbee" else (DD() if platform == "dd" else (Blackbox() if platform == "blackbox" else (CurseForge() if platform == "curseforge" else _modus_provider())))
            try:
                if platform == "dd":
                    data = provider.execute_write(resource, action, doc, getattr(args, "session", None))
                else:
                    data = provider.execute_write(resource, action, doc)
            finally:
                close = getattr(provider, "close", None)
                if close:
                    close()
            write_output(platform, operation, data)
            return 0
        modus_doctor = platform == "modus" and resource == "session" and action == "doctor"
        provider = NewBee() if platform == "newbee" else (DD() if platform == "dd" else (Blackbox() if platform == "blackbox" else (CurseForge() if platform == "curseforge" else _modus_provider(authenticate=not modus_doctor))))
        try:
            if platform == "dd":
                data = provider.execute_read(resource, action, args, getattr(args, "session", None))
            else:
                data = provider.execute_read(resource, action, args)
        finally:
            close = getattr(provider, "close", None)
            if close:
                close()
        write_output(platform, operation, data)
        return 0
    except (FuploadError, OSError, ValueError) as exc:
        write_error(platform, operation, exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
