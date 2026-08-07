import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { clearManagedInstall, readManagedInstall } from "./managed-install.mjs";
import { resolveSkillDirectory } from "./options.mjs";
import { removePythonRuntime } from "./python.mjs";
import { INSTALL_STAMP, INSTALL_STAMP_SCHEMA, readInstallStamp } from "./skill-installer.mjs";

export const PACKAGE_NAME = "@follenfang/fupload";

export class ManagedUninstallError extends Error {
  constructor(message, details) {
    super(message);
    this.name = "ManagedUninstallError";
    this.code = "FUPLOAD_UNINSTALL_FAILED";
    this.details = details;
  }
}

export function inspectManagedSkill(target) {
  const resolved = path.resolve(target);
  if (resolved === path.parse(resolved).root) {
    return { target: resolved, status: "preserved_unmanaged", reason: "filesystem_root" };
  }
  if (!fs.existsSync(resolved)) {
    return { target: resolved, status: "missing" };
  }
  const stamp = readInstallStamp(resolved);
  if (
    stamp?.schema !== INSTALL_STAMP_SCHEMA ||
    stamp?.package_name !== PACKAGE_NAME ||
    path.resolve(stamp?.target || "") !== resolved
  ) {
    return { target: resolved, status: "preserved_unmanaged", reason: "ownership_unknown" };
  }
  return { target: resolved, status: "managed", marker: path.join(resolved, INSTALL_STAMP) };
}

export async function cleanupManagedSkills({
  platform = process.platform,
  env = process.env,
  home = os.homedir(),
  extraTargets = [],
  removePath = (target) => fs.rmSync(target, { recursive: true, force: true }),
} = {}) {
  const registry = readManagedInstall({ platform, env, home });
  const targets = [
    ...new Set([
      ...registry.targets
        .filter((entry) => typeof entry?.path === "string")
        .map((entry) => path.resolve(entry.path)),
      path.resolve(resolveSkillDirectory({ env, home })),
      ...extraTargets.map((target) => path.resolve(target)),
    ]),
  ];
  const result = {
    schema: "fupload.npm-cleanup-result.v1",
    skills: [],
    project_data: "preserved",
    platform_credentials: "preserved",
    platform_logs: "preserved",
  };
  for (const target of targets) {
    const inspection = inspectManagedSkill(target);
    if (inspection.status !== "managed") {
      result.skills.push(inspection);
      continue;
    }
    try {
      removePath(inspection.target);
      if (fs.existsSync(inspection.target)) {
        throw new Error("path still exists after deletion");
      }
      result.skills.push({ target: inspection.target, status: "removed" });
    } catch (error) {
      result.skills.push({ target: inspection.target, status: "failed" });
      throw new ManagedUninstallError("A managed Fuploader Skill could not be removed.", {
        result,
        object: inspection.target,
        reason: error.message,
      });
    }
  }
  clearManagedInstall({ platform, env, home });
  return result;
}

export function resolveGlobalInstall(packageRoot, platform = process.platform) {
  let current = path.resolve(packageRoot);
  let nodeModules;
  while (true) {
    if (path.basename(current).toLowerCase() === "node_modules") {
      nodeModules = current;
      break;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }
  if (!nodeModules) {
    throw new ManagedUninstallError("The npm installation prefix could not be resolved.", {
      package_root: path.resolve(packageRoot),
    });
  }
  let prefix = path.dirname(nodeModules);
  if (platform !== "win32" && path.basename(prefix) === "lib") {
    prefix = path.dirname(prefix);
  }
  const launcher = platform === "win32"
    ? path.join(prefix, "fupload.cmd")
    : path.join(prefix, "bin", "fupload");
  if (!fs.existsSync(launcher)) {
    throw new ManagedUninstallError("fupload uninstall requires a global npm installation.", {
      package_root: path.resolve(packageRoot),
      prefix,
      launcher,
    });
  }
  return { prefix, launcher, packageRoot: path.resolve(packageRoot) };
}

export function resolveNpmCli({
  platform = process.platform,
  env = process.env,
  run = spawnSync,
} = {}) {
  if (env.npm_execpath && fs.existsSync(env.npm_execpath)) {
    return path.resolve(env.npm_execpath);
  }
  if (platform === "win32") {
    const located = run("where.exe", ["npm.cmd"], { encoding: "utf8", windowsHide: true });
    if (located.status === 0) {
      for (const shim of located.stdout.split(/\r?\n/).filter(Boolean)) {
        const candidate = path.join(path.dirname(shim.trim()), "node_modules", "npm", "bin", "npm-cli.js");
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      }
    }
  } else {
    const located = run("which", ["npm"], { encoding: "utf8" });
    if (located.status === 0) {
      try {
        const candidate = fs.realpathSync(located.stdout.trim());
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      } catch {
        // Fall through to the stable error below.
      }
    }
  }
  throw new ManagedUninstallError("npm-cli.js could not be located for self-removal.");
}

export function runNpmCli(args, { platform = process.platform, env = process.env } = {}) {
  return spawnSync(process.execPath, [resolveNpmCli({ platform, env }), ...args], {
    encoding: "utf8", env, shell: false, windowsHide: true,
  });
}

function bounded(value) {
  return String(value || "").trim().slice(0, 4000);
}

export async function uninstallSelf({
  packageRoot,
  target,
  platform = process.platform,
  env = process.env,
  home = os.homedir(),
  runNpm = runNpmCli,
  removeRuntime = removePythonRuntime,
} = {}) {
  const installation = resolveGlobalInstall(packageRoot, platform);
  const cleanup = await cleanupManagedSkills({
    platform,
    env,
    home,
    extraTargets: target ? [target] : [],
  });
  let runtime;
  try {
    runtime = removeRuntime({ platform, env, home });
  } catch (error) {
    throw new ManagedUninstallError("The managed Fuploader Python runtime could not be removed.", {
      cleanup,
      reason: error.message,
    });
  }
  const args = ["uninstall", "-g", "--ignore-scripts", "--prefix", installation.prefix, PACKAGE_NAME];
  const npmResult = runNpm(args, { platform, env });
  if (npmResult.error || npmResult.status !== 0) {
    throw new ManagedUninstallError("npm could not remove the Fuploader package and CLI.", {
      cleanup,
      prefix: installation.prefix,
      exit_status: npmResult.status,
      stdout: bounded(npmResult.stdout),
      stderr: bounded(npmResult.stderr || npmResult.error?.message),
    });
  }
  const residuals = [installation.launcher, installation.packageRoot].filter((candidate) => fs.existsSync(candidate));
  if (residuals.length) {
    throw new ManagedUninstallError("npm reported success but Fuploader installation files remain.", {
      cleanup,
      prefix: installation.prefix,
      residuals,
    });
  }
  return {
    schema: "fupload.npm-uninstall-result.v1",
    success: true,
    package: PACKAGE_NAME,
    prefix: installation.prefix,
    cleanup,
    python_runtime: runtime,
    npm_exit_status: npmResult.status,
  };
}
