import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { productStateRoot } from "./managed-install.mjs";

export const PYTHON_RUNTIME_SCHEMA = "fupload.python-runtime.v2";
const RUNTIME_DIRECTORY = "python";
const RUNTIME_MARKER = "runtime.json";
const RUNTIME_LOCK_WAIT_MS = 5 * 60 * 1000;
const RUNTIME_LOCK_STALE_MS = 15 * 60 * 1000;

function probe(command, args, minimum) {
  const result = spawnSync(command, [...args, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"], {
    encoding: "utf8",
    shell: false,
    windowsHide: true,
  });
  if (result.status !== 0) {
    return null;
  }
  const match = result.stdout.trim().match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) {
    return null;
  }
  const version = match.slice(1).map(Number);
  if (version[0] !== 3 || version[1] < minimum) {
    return null;
  }
  return { command, args, version };
}

export function discoverPython({ platform = process.platform, minimumMinor = 9 } = {}) {
  const candidates = platform === "win32"
    ? [["python", []], ["py", ["-3"]], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [command, args] of candidates) {
    const result = probe(command, args, minimumMinor);
    if (result) {
      return result;
    }
  }
  return null;
}

export function discoverUv({ run = spawnSync } = {}) {
  const result = run("uv", ["--version"], {
    encoding: "utf8",
    shell: false,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    return null;
  }
  const match = result.stdout.trim().match(/^uv (\d+)\.(\d+)\.(\d+)(?:\s|$)/);
  if (!match) {
    return null;
  }
  return { command: "uv", args: [], version: match.slice(1).map(Number) };
}

export function runPython(python, script, args, options = {}) {
  const run = options.run || spawnSync;
  const env = options.runtimeRoot
    ? runtimeEnvironment(options.runtimeRoot, options.env || process.env)
    : options.env || process.env;
  return run(python.command, [...python.args, script, ...args], {
    cwd: options.cwd || process.cwd(),
    env,
    stdio: options.stdio || "inherit",
    encoding: options.encoding,
    shell: false,
    windowsHide: true,
  });
}

export function pythonRequirementsFile(packageRoot) {
  return path.join(packageRoot, "npm", "lib", "python-requirements.txt");
}

export function pythonRuntimeRoot(options = {}) {
  return path.join(productStateRoot(options), RUNTIME_DIRECTORY);
}

export function pythonRuntimeExecutable(root, platform = process.platform) {
  return platform === "win32"
    ? path.join(root, "Scripts", "python.exe")
    : path.join(root, "bin", "python");
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function readMarker(root) {
  try {
    return JSON.parse(fs.readFileSync(path.join(root, RUNTIME_MARKER), "utf8"));
  } catch {
    return null;
  }
}

function runtimeEnvironment(root, env) {
  return {
    ...env,
    PLAYWRIGHT_BROWSERS_PATH: path.join(root, "browsers"),
  };
}

function probeRuntime(executable, root, env, run = spawnSync) {
  if (!fs.existsSync(executable)) {
    return null;
  }
  const result = run(executable, [
    "-c",
    "import importlib.metadata,json,pathlib,sys; import qcloud_cos; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); executable=p.chromium.executable_path; p.stop(); print(json.dumps({'python_version': '.'.join(map(str,sys.version_info[:3])), 'cos_version': importlib.metadata.version('cos-python-sdk-v5'), 'playwright_version': importlib.metadata.version('playwright'), 'chromium_executable': executable})); sys.exit(0 if pathlib.Path(executable).is_file() else 1)",
  ], {
    encoding: "utf8",
    env: runtimeEnvironment(root, env),
    shell: false,
    windowsHide: true,
  });
  if (result.status !== 0) {
    return null;
  }
  let details;
  try {
    details = JSON.parse(result.stdout.trim());
  } catch {
    return null;
  }
  const match = details.python_version?.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match || !details.cos_version || !details.playwright_version || !details.chromium_executable) {
    return null;
  }
  return {
    version: match.slice(1).map(Number),
    dependencyVersion: details.cos_version,
    playwrightVersion: details.playwright_version,
    chromiumExecutable: details.chromium_executable,
  };
}

function inspectRuntime({ root, platform, requirementsHash, env, run }) {
  const marker = readMarker(root);
  if (
    marker?.schema !== PYTHON_RUNTIME_SCHEMA ||
    marker.requirements_sha256 !== requirementsHash
  ) {
    return null;
  }
  const command = pythonRuntimeExecutable(root, platform);
  const probe = probeRuntime(command, root, env, run);
  if (!probe || probe.version[0] !== 3 || probe.version[1] < 9) {
    return null;
  }
  return { command, args: [], ...probe };
}

function bounded(value) {
  return String(value || "").trim().slice(0, 4000);
}

function runChecked(run, command, args, message, options = {}) {
  const result = run(command, args, {
    encoding: "utf8",
    ...options,
    shell: false,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    const detail = bounded(result.stderr || result.stdout || result.error?.message);
    throw new Error(`${message}${detail ? `: ${detail}` : ""}`);
  }
  return result;
}

function writeMarker(root, value) {
  fs.writeFileSync(path.join(root, RUNTIME_MARKER), `${JSON.stringify(value, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
}

function sleepSync(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

function acquireRuntimeLock(root) {
  const lock = `${root}.lock`;
  fs.mkdirSync(path.dirname(root), { recursive: true });
  const deadline = Date.now() + RUNTIME_LOCK_WAIT_MS;
  while (Date.now() < deadline) {
    try {
      const descriptor = fs.openSync(lock, "wx", 0o600);
      fs.writeFileSync(descriptor, `${JSON.stringify({ pid: process.pid })}\n`);
      return {
        release() {
          fs.closeSync(descriptor);
          fs.rmSync(lock, { force: true });
        },
      };
    } catch (error) {
      if (error.code !== "EEXIST") {
        throw error;
      }
      try {
        if (Date.now() - fs.statSync(lock).mtimeMs > RUNTIME_LOCK_STALE_MS) {
          fs.rmSync(lock, { force: true });
          continue;
        }
      } catch (statError) {
        if (statError.code !== "ENOENT") {
          throw statError;
        }
      }
      sleepSync(50);
    }
  }
  throw new Error(`Timed out waiting for the Fuploader Python runtime lock: ${lock}`);
}

export function ensurePythonRuntime({
  packageRoot,
  platform = process.platform,
  env = process.env,
  home = os.homedir(),
  run = spawnSync,
  discover = discoverPython,
  discoverUv: locateUv = discoverUv,
} = {}) {
  const requirements = pythonRequirementsFile(packageRoot);
  const content = fs.readFileSync(requirements);
  const requirementsHash = sha256(content);
  const root = pythonRuntimeRoot({ platform, env, home });
  const parent = path.dirname(root);
  const lock = acquireRuntimeLock(root);
  try {
    const uv = locateUv({ run });
    const dependencyInstaller = uv ? "uv" : "pip";
    const current = inspectRuntime({
      root,
      platform,
      requirementsHash,
      env,
      run,
    });
    if (current) {
      return { status: "current", root, requirements, python: current };
    }

    const base = discover({ platform });
    if (!base) {
      throw new Error("Fuploader requires Python >=3.9,<4.0 to create its managed runtime.");
    }
    const nonce = `${process.pid}-${crypto.randomBytes(8).toString("hex")}`;
    const staging = path.join(parent, `.python-stage-${nonce}`);
    const backup = path.join(parent, `.python-backup-${nonce}`);
    fs.mkdirSync(parent, { recursive: true });
    let movedOld = false;
    let created;
    try {
      runChecked(run, base.command, [...base.args, "-m", "venv", staging], "Could not create the Fuploader Python runtime");
      const stagingPython = pythonRuntimeExecutable(staging, platform);
      if (uv) {
        runChecked(run, uv.command, [
          ...uv.args,
          "pip", "install",
          "--python", stagingPython,
          "--requirements", requirements,
          "--link-mode", "copy",
          "--no-config",
          "--no-progress",
          "--no-python-downloads",
        ], "Could not install Fuploader Python dependencies with uv");
      } else {
        runChecked(run, stagingPython, [
          "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--requirement", requirements,
        ], "Could not install Fuploader Python dependencies");
      }
      runChecked(run, stagingPython, [
        "-m", "playwright", "install", "chromium",
      ], "Could not install Fuploader Chromium", {
        env: runtimeEnvironment(staging, env),
      });
      const installed = probeRuntime(stagingPython, staging, env, run);
      if (!installed) {
        throw new Error("The Fuploader Python runtime did not pass its dependency probe.");
      }
      writeMarker(staging, {
        schema: PYTHON_RUNTIME_SCHEMA,
        requirements_sha256: requirementsHash,
        dependency_installer: dependencyInstaller,
        dependency_installer_version: uv ? uv.version.join(".") : null,
        python_version: installed.version.join("."),
        dependency_version: installed.dependencyVersion,
        playwright_version: installed.playwrightVersion,
        chromium_executable: path.relative(staging, installed.chromiumExecutable),
      });
      if (fs.existsSync(root)) {
        fs.renameSync(root, backup);
        movedOld = true;
      }
      try {
        fs.renameSync(staging, root);
      } catch (error) {
        if (movedOld && !fs.existsSync(root)) {
          fs.renameSync(backup, root);
          movedOld = false;
        }
        throw error;
      }
      created = inspectRuntime({
        root,
        platform,
        requirementsHash,
        env,
        run,
      });
      if (!created) {
        fs.rmSync(root, { recursive: true, force: true });
        if (movedOld) {
          fs.renameSync(backup, root);
          movedOld = false;
        }
        throw new Error("The installed Fuploader Python runtime failed final validation.");
      }
      if (movedOld) {
        fs.rmSync(backup, { recursive: true, force: true });
      }
    } finally {
      fs.rmSync(staging, { recursive: true, force: true });
    }
    return { status: "installed", root, requirements, python: created };
  } finally {
    lock.release();
  }
}

export function removePythonRuntime({ platform = process.platform, env = process.env, home = os.homedir() } = {}) {
  const productRoot = productStateRoot({ platform, env, home });
  const root = pythonRuntimeRoot({ platform, env, home });
  const lock = acquireRuntimeLock(root);
  try {
    fs.rmSync(root, { recursive: true, force: true });
  } finally {
    lock.release();
  }
  try {
    if (fs.readdirSync(productRoot).length === 0) {
      fs.rmdirSync(productRoot);
    }
  } catch (error) {
    if (error.code !== "ENOENT" && error.code !== "ENOTEMPTY") {
      throw error;
    }
  }
  return { root, status: "removed" };
}
