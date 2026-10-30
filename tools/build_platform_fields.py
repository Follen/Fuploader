"""Build the public field catalog from executable schemas and audited wire maps.

Only code and public audit metadata are read. No account/session files are used.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fupload/scripts"))
from fupload_cli.schema import SCHEMAS
from fupload_cli.cli import build_parser

TARGET = ROOT / "fupload/references/platform-fields.md"
AUDITS = ROOT / "docs/platform-audit"
PLATFORMS = {"newbee": "新手盒子", "dd": "网易 DD", "blackbox": "黑盒工坊", "modus": "ModUs 与 Creator", "curseforge": "CurseForge"}


def esc(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def code(value):
    return "`" + esc(value) + "`"


def audits():
    result = {name: {"fields": {}, "actions": {}} for name in PLATFORMS}
    for path in sorted(AUDITS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        bundles = data.get("platforms") if isinstance(data, dict) else None
        bundles = bundles if isinstance(bundles, dict) else {data.get("platform", path.stem): data}
        for platform, bundle in bundles.items():
            if platform in result:
                if "fields" not in bundle and any("." in key and isinstance(value, dict) and "wire" in value for key, value in bundle.items()):
                    bundle = {"fields": bundle}
                for kind in ("fields", "actions"):
                    result[platform][kind].update(bundle.get(kind, {}))
                if "official_cli" in bundle:
                    result[platform]["official_cli"] = bundle["official_cli"]
    return result


def wire_entry(data, resource, action, name):
    for key in (f"{resource}.{action}.{name}", f"{resource}.*.{name}", f"*.{action}.{name}", f"*.*.{name}"):
        if key in data["fields"]:
            entry = data["fields"][key]
            return {"wire": entry} if isinstance(entry, str) else entry
    return {"wire": "待核对", "evidence": "尚无已核对的协议映射"}


def leaves(parser, prefix=()):
    children = [item for item in parser._actions if isinstance(item, argparse._SubParsersAction)]
    if not children:
        yield prefix, parser
    for child in children:
        for name, nested in child.choices.items():
            yield from leaves(nested, prefix + (name,))


def constraints(field):
    parts = []
    if field.nonempty:
        parts.append("非空")
    if field.choices:
        parts.append("可选 " + code(json.dumps(field.choices, ensure_ascii=False)))
    for attr, label in (("minimum", "最小"), ("maximum", "最大"), ("max_length", "最多字符"), ("max_items", "最多项")):
        value = getattr(field, attr)
        if value is not None:
            parts.append(label + " " + str(value))
    if field.local_file:
        parts.append("本机存在的普通文件")
    if field.description:
        parts.append(esc(field.description))
    return "；".join(parts) or "见动作条件及嵌套结构"


def render():
    metadata = audits()
    commands = list(leaves(build_parser()))
    rows = ["# 平台字段与登录契约", "", "核对日期：2026-10-30。此表覆盖 Fupload 作者发布、配置分享、WA 与云备份命令，不把客户端其它业务算作已支持。", "",
            f"当前共 **{len(SCHEMAS)} 个写入动作、{sum(len(item.fields) for item in SCHEMAS.values())} 个动作字段位置**。字段在不同动作中出现时分别列出，必填性可能不同。", "",
            "本文件由 `tools/build_platform_fields.py` 根据可执行 Schema、CLI 命令树和 `docs/platform-audit/*.json` 的协议核对记录生成。修改字段后运行生成器；`--check` 检查是否同步。", "",
            "## 使用规则", "",
            "- 写命令使用 `--input <JSON文件>|-`；首项 `schema` 必须与动作完全匹配。`--dry-run` 只核对本机结构，不执行登录、上传或远程验证。",
            "- 必填、允许 null 和条件必填是不同概念。省略字段的含义由动作决定；不要将省略一律替换成空字符串、空数组或 false。",
            "- 备份 ID、插件 ID、版本 ID、配置 ID 及本地备份 ID 分开使用。动态版本、分类、套餐、账号角色和频道先查询，不照抄历史编号。",
            "- 备份删除必须使用明确 ID 与 `confirm_delete=true`。已被配置分享引用的备份禁止删除；查询不完整时停止。",
            "- 手机号、验证码、Cookie、pkey、token、签名上传地址不进入输出、样例或版本库。登录待办只返回不透明任务编号、状态和二维码图片路径。", "",
            "## 平台索引", ""]
    for platform, title in PLATFORMS.items():
        rows.append(f"- [{title}](#{platform})")
    missing = []
    for platform, title in PLATFORMS.items():
        rows += ["", f'<a id="{platform}"></a>', f"## {title}", ""]
        notes = AUDITS / (platform + ".md")
        if not notes.exists() and platform in ("modus", "curseforge"):
            combined = (AUDITS / "modus-curseforge.md").read_text(encoding="utf-8")
            heading = "ModUs" if platform == "modus" else "CurseForge"
            text = combined.split("## " + heading + "\n", 1)[1].split("\n## ", 1)[0].strip()
            rows += [text, ""]
        if notes.exists():
            text = notes.read_text(encoding="utf-8").strip()
            if text.startswith("# "):
                text = text.split("\n", 1)[1].lstrip()
            # Place audit headings under the platform, without duplicating H1/H2.
            text = re.sub(r"\[([^\]]+\.json)\]\(([^)]+\.json)\)",
                          lambda match: code("docs/platform-audit/" + match.group(2)), text)
            text = "\n".join("#" + line if line.startswith("#") else line for line in text.splitlines())
            rows += [text, ""]
        official = metadata[platform].get("official_cli")
        if official:
            rows += ["### 官方 NCC 命令参数", "", f"本机只读核对版本：{code(official['version'])}。以下是官方 CLI 的独立入口，不能当作 Python JSON 字段使用。完整位置参数与配置说明见 [NCC 官方文档快照](newbee-official-cli.md)。", "",
                     "| 官方命令 | 参数 | 含义 |", "| --- | --- | --- |"]
            for command, definition in official["commands"].items():
                options = [item for item in definition.get("options", []) if item["flags"] != "-h, --help"]
                if not options:
                    rows.append(f"| {code(command)} | 无额外选项 | 位置参数见官方快照 |")
                for option in options:
                    rows.append(f"| {code(command)} | {code(option['flags'])} | {esc(option['description'])} |")
            rows += ["", "依据：本机官方 NCC 各叶子命令 `--help`，未触发登录或业务写入。", ""]
        rows += ["### 只读命令与输入参数", "", "| 命令 | 参数 | 默认/必填 |", "| --- | --- | --- |"]
        for command, leaf in commands:
            if command[0] != platform or leaf.get_default("handler") != "read":
                continue
            options = [item for item in leaf._actions if item.dest != "help"]
            if not options:
                rows.append(f"| {code(' '.join(command))} | 无额外参数 | — |")
            for option in options:
                default = "必填" if option.required else "不传" if option.default is None else json.dumps(option.default, ensure_ascii=False)
                choice = "；可选 " + json.dumps(option.choices, ensure_ascii=False) if option.choices is not None else ""
                rows.append(f"| {code(' '.join(command))} | {code('/'.join(option.option_strings) or option.dest)} | {esc(default + choice)} |")
        for (plat, resource, action), schema in sorted(SCHEMAS.items()):
            if plat != platform:
                continue
            rows += ["", f'<a id="{platform}-{resource}-{action}"></a>', f"### `{resource} {action}`", "", "Schema：" + code(schema.name) + "。"]
            action_info = metadata[platform]["actions"].get(resource + "." + action, {})
            if isinstance(action_info, str):
                rows += ["", esc(action_info)]
            elif action_info:
                for label, name in (("接口", "endpoint"), ("条件和省略规则", "condition"), ("依据", "evidence")):
                    if action_info.get(name):
                        rows += ["", label + "：" + esc(action_info[name])]
            rows += ["", "| CLI JSON 字段 | 类型 | 必填 | null | 约束 | 接口字段/用途 |", "| --- | --- | --- | --- | --- | --- |"]
            sources = set()
            for name, field in schema.fields.items():
                entry = wire_entry(metadata[platform], resource, action, name)
                wire = entry.get("wire", "待核对")
                if wire in ("待核对", "unknown", None):
                    missing.append(f"{platform}.{resource}.{action}.{name}")
                details = esc(wire)
                for extra in ("stage", "condition"):
                    if entry.get(extra):
                        details += "；" + esc(entry[extra])
                if entry.get("evidence"):
                    sources.add(str(entry["evidence"]))
                rows.append(f"| {code(name)} | {code(field.type)} | {'是' if field.required else '否/条件必填'} | {'允许' if field.nullable else '拒绝'} | {constraints(field)} | {details} |")
            if sources:
                rows += ["", "字段映射依据：" + "；".join(code(source) for source in sorted(sources)) + "。"]
        positions = [f"{resource}.{action}.{name}" for (plat, resource, action), schema in SCHEMAS.items()
                     if plat == platform for name in schema.fields]
        extra = {key: value for key, value in metadata[platform]["fields"].items()
                 if not any(fnmatch.fnmatchcase(position, key) for position in positions)}
        if extra:
            rows += ["", "### 补充嵌套或协议字段", "", "以下不是额外的顶层 JSON 字段；是否可由用户填写，以对应对象结构和动作说明为准。", "",
                     "| 字段路径 | 接口字段/用途 | 条件 | 依据 |", "| --- | --- | --- | --- |"]
            for key, value in sorted(extra.items()):
                entry = {"wire": value} if isinstance(value, str) else value
                rows.append(f"| {code(key)} | {esc(entry.get('wire', '待核对'))} | {esc(entry.get('condition', ''))} | {code(entry.get('evidence', ''))} |")
    rows += ["", "## 覆盖检查", "", f"已列出 {len(SCHEMAS)} 个 Schema 的全部字段。尚待核对的协议映射：{len(missing)} 个动作字段位置。"]
    if missing:
        rows += ["", "以下字段不据名称推测接口含义：", ""] + ["- " + code(name) for name in missing]
    return "\n".join(rows) + "\n", missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Reject unverified wire mappings")
    args = parser.parse_args()
    content, missing = render()
    if args.strict and missing:
        raise SystemExit(f"Unverified wire mappings: {len(missing)}")
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != content:
            raise SystemExit("Platform field reference is stale")
    else:
        TARGET.write_text(content, encoding="utf-8")
    print(f"Platform fields: {len(SCHEMAS)} schemas; {len(missing)} unverified mappings")


if __name__ == "__main__":
    main()
