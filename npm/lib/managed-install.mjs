import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const MANAGED_INSTALL_SCHEMA = "fupload.npm-managed-install.v1";
export const MANAGED_INSTALL_FILE = "managed-install.json";
const PACKAGE_NAME = "@follenfang/fupload";

function stateRoot({ platform = process.platform, env = process.env, home = os.homedir() } = {}) {
  if (platform === "win32") {
    return path.join(env.LOCALAPPDATA || path.join(home, "AppData", "Local"), "Fupload", "npm");
  }
  return path.join(env.XDG_STATE_HOME || path.join(home, ".local", "state"), "fupload", "npm");
}

function atomicWriteJson(filename, value) {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  const temporary = `${filename}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  fs.renameSync(temporary, filename);
}

export function managedInstallFile(options = {}) {
  return path.join(stateRoot(options), MANAGED_INSTALL_FILE);
}

export function readManagedInstall(options = {}) {
  const filename = options.filename || managedInstallFile(options);
  try {
    const value = JSON.parse(fs.readFileSync(filename, "utf8"));
    if (
      value?.schema !== MANAGED_INSTALL_SCHEMA ||
      value?.package_name !== PACKAGE_NAME ||
      !Array.isArray(value.targets)
    ) {
      throw new Error("unsupported schema");
    }
    return value;
  } catch (error) {
    if (error.code === "ENOENT") {
      return { schema: MANAGED_INSTALL_SCHEMA, package_name: PACKAGE_NAME, targets: [] };
    }
    throw new Error(`Managed Skill registry is invalid: ${filename}`, { cause: error });
  }
}

export function recordManagedSkill(target, options = {}) {
  const filename = options.filename || managedInstallFile(options);
  const resolved = path.resolve(target);
  if (resolved === path.parse(resolved).root) {
    throw new Error("A filesystem root cannot be registered as a managed Skill.");
  }
  const state = readManagedInstall({ ...options, filename });
  const targets = state.targets
    .filter((entry) => typeof entry?.path === "string" && path.resolve(entry.path) !== resolved)
    .map((entry) => ({ path: path.resolve(entry.path), registered_at: entry.registered_at }));
  targets.push({ path: resolved, registered_at: new Date().toISOString() });
  targets.sort((left, right) => left.path.localeCompare(right.path));
  atomicWriteJson(filename, {
    schema: MANAGED_INSTALL_SCHEMA,
    package_name: PACKAGE_NAME,
    targets,
  });
  return { filename, target: resolved, count: targets.length };
}

export function clearManagedInstall(options = {}) {
  const filename = options.filename || managedInstallFile(options);
  fs.rmSync(filename, { force: true });
  const npmState = path.dirname(filename);
  const productState = path.dirname(npmState);
  for (const directory of [npmState, productState]) {
    try {
      if (fs.readdirSync(directory).length === 0) {
        fs.rmdirSync(directory);
      }
    } catch (error) {
      if (error.code !== "ENOENT" && error.code !== "ENOTEMPTY") {
        throw error;
      }
    }
  }
}
