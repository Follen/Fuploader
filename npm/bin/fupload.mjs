#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";

import { ensureCurseForgeEnv } from "../lib/curseforge-config.mjs";
import { recordManagedSkill } from "../lib/managed-install.mjs";
import { parseLauncherOptions, resolveSkillDirectory } from "../lib/options.mjs";
import { discoverPython, runPython } from "../lib/python.mjs";
import { ensureSkill } from "../lib/skill-installer.mjs";
import { uninstallSelf } from "../lib/uninstall.mjs";
import { updateSelf } from "../lib/update.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function emitError(code, message, details = undefined) {
  const record = { event: "error", code, message };
  if (details) {
    record.details = details;
  }
  process.stderr.write(`${JSON.stringify(record)}\n`);
}

async function main() {
  let options;
  try {
    options = parseLauncherOptions(process.argv.slice(2));
  } catch (error) {
    emitError("LAUNCHER_ARGUMENT_INVALID", error.message);
    return 2;
  }
  const target = resolveSkillDirectory({ explicit: options.skillDirectory });
  if (options.forwarded.length === 1 && options.forwarded[0] === "update") {
    try {
      const result = await updateSelf({ packageRoot, target });
      process.stdout.write(`${JSON.stringify(result)}\n`);
      return 0;
    } catch (error) {
      emitError(error.code || "FUPLOAD_UPDATE_FAILED", error.message, error.details);
      return 1;
    }
  }
  if (options.forwarded.length === 1 && options.forwarded[0] === "uninstall") {
    try {
      const result = await uninstallSelf({ packageRoot, target });
      process.stdout.write(`${JSON.stringify(result)}\n`);
      return 0;
    } catch (error) {
      emitError(error.code || "FUPLOAD_UNINSTALL_FAILED", error.message, error.details);
      return 1;
    }
  }

  let ensured;
  try {
    ensureCurseForgeEnv();
    ensured = await ensureSkill({ packageRoot, target });
    recordManagedSkill(target);
  } catch (error) {
    emitError("SKILL_INSTALL_FAILED", error.message, { target });
    return 1;
  }
  if (options.forwarded.length === 1 && options.forwarded[0] === "--version") {
    process.stdout.write(`${ensured.distribution.packageRecord.version}\n`);
    return 0;
  }

  const python = discoverPython();
  if (!python) {
    emitError(
      "PYTHON_VERSION_UNSUPPORTED",
      "Fuploader requires Python >=3.9,<4.0. Install Python and run the command again.",
    );
    return 1;
  }
  const script = path.join(target, "scripts", "fupload.py");
  const result = runPython(python, script, options.forwarded);
  if (result.error) {
    emitError("PYTHON_LAUNCH_FAILED", result.error.message);
    return 1;
  }
  if (
    result.status === 0 &&
    options.forwarded.length === 1 &&
    ["--help", "-h"].includes(options.forwarded[0])
  ) {
    process.stdout.write("\nnpm management:\n  fupload update     Update this CLI and all managed Skills.\n  fupload uninstall  Remove managed Skills, this CLI, and its npm package.\n");
  }
  return result.status ?? 1;
}

process.exitCode = await main();
