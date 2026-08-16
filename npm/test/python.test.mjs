import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  discoverPython,
  ensurePythonRuntime,
  pythonRuntimeExecutable,
  pythonRuntimeRoot,
  removePythonRuntime,
  runPython,
} from "../lib/python.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

test("discovers a supported local Python interpreter", () => {
  const python = discoverPython();
  assert.ok(python);
  assert.equal(python.version[0], 3);
  assert.ok(python.version[1] >= 9);
});

test("launches managed Python with its Chromium directory", () => {
  const runtimeRoot = path.join("state", "python");
  let invocation;
  const result = runPython(
    { command: "managed-python", args: ["-I"] },
    "fupload.py",
    ["blackbox", "plugin", "list"],
    {
      cwd: "workspace",
      env: { EXISTING_VALUE: "preserved" },
      runtimeRoot,
      run(command, args, options) {
        invocation = { command, args, options };
        return { status: 0 };
      },
    },
  );

  assert.equal(result.status, 0);
  assert.equal(invocation.command, "managed-python");
  assert.deepEqual(invocation.args, [
    "-I",
    "fupload.py",
    "blackbox",
    "plugin",
    "list",
  ]);
  assert.equal(invocation.options.cwd, "workspace");
  assert.equal(invocation.options.env.EXISTING_VALUE, "preserved");
  assert.equal(
    invocation.options.env.PLAYWRIGHT_BROWSERS_PATH,
    path.join(runtimeRoot, "browsers"),
  );
  assert.equal(invocation.options.shell, false);
  assert.equal(invocation.options.windowsHide, true);
});

test("creates, reuses, and removes the managed Python runtime", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-python-runtime-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const options = {
    packageRoot,
    platform: "linux",
    env: { XDG_STATE_HOME: path.join(root, "state") },
    home: path.join(root, "home"),
  };
  let venvCreates = 0;
  let chromiumInstalls = 0;
  function run(command, args, runOptions = {}) {
    if (args.includes("venv")) {
      const staging = args.at(-1);
      fs.mkdirSync(path.dirname(pythonRuntimeExecutable(staging, "linux")), { recursive: true });
      fs.writeFileSync(pythonRuntimeExecutable(staging, "linux"), "python", "utf8");
      venvCreates += 1;
      return { status: 0, stdout: "", stderr: "" };
    }
    if (args.includes("pip")) {
      return { status: 0, stdout: "installed", stderr: "" };
    }
    if (args.includes("playwright") && args.includes("install")) {
      const executable = path.join(runOptions.env.PLAYWRIGHT_BROWSERS_PATH, "chromium-test", "chrome");
      fs.mkdirSync(path.dirname(executable), { recursive: true });
      fs.writeFileSync(executable, "chromium", "utf8");
      chromiumInstalls += 1;
      return { status: 0, stdout: "installed", stderr: "" };
    }
    const executable = path.join(runOptions.env.PLAYWRIGHT_BROWSERS_PATH, "chromium-test", "chrome");
    return {
      status: fs.existsSync(executable) ? 0 : 1,
      stdout: `${JSON.stringify({
        python_version: "3.12.0",
        cos_version: "1.9.44",
        playwright_version: "1.62.0",
        chromium_executable: executable,
      })}\n`,
      stderr: "",
    };
  }
  const discover = () => ({ command: "base-python", args: [], version: [3, 12, 0] });
  const installed = ensurePythonRuntime({ ...options, run, discover });
  assert.equal(installed.status, "installed");
  assert.equal(installed.root, pythonRuntimeRoot(options));
  assert.equal(installed.python.dependencyVersion, "1.9.44");
  assert.equal(installed.python.playwrightVersion, "1.62.0");
  assert.ok(fs.existsSync(installed.python.chromiumExecutable));
  const current = ensurePythonRuntime({ ...options, run, discover });
  assert.equal(current.status, "current");
  assert.equal(venvCreates, 1);
  assert.equal(chromiumInstalls, 1);
  fs.rmSync(installed.python.chromiumExecutable);
  const repaired = ensurePythonRuntime({ ...options, run, discover });
  assert.equal(repaired.status, "installed");
  assert.ok(fs.existsSync(repaired.python.chromiumExecutable));
  assert.equal(venvCreates, 2);
  assert.equal(chromiumInstalls, 2);
  const removed = removePythonRuntime(options);
  assert.equal(removed.status, "removed");
  assert.equal(fs.existsSync(installed.root), false);
});

test("keeps the existing runtime when Chromium installation fails", (t) => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-python-runtime-rollback-test-"));
  t.after(() => fs.rmSync(temporary, { recursive: true, force: true }));
  const packageRoot = path.join(temporary, "package");
  const requirements = path.join(packageRoot, "npm", "lib", "python-requirements.txt");
  fs.mkdirSync(path.dirname(requirements), { recursive: true });
  fs.writeFileSync(requirements, "cos-python-sdk-v5==1.9.44\nplaywright==1.62.0\n", "utf8");
  const options = {
    packageRoot,
    platform: "linux",
    env: { XDG_STATE_HOME: path.join(temporary, "state") },
    home: path.join(temporary, "home"),
  };
  let failChromium = false;
  let failFinalProbe = false;
  function run(command, args, runOptions = {}) {
    if (args.includes("venv")) {
      const staging = args.at(-1);
      fs.mkdirSync(path.dirname(pythonRuntimeExecutable(staging, "linux")), { recursive: true });
      fs.writeFileSync(pythonRuntimeExecutable(staging, "linux"), "python", "utf8");
      return { status: 0, stdout: "", stderr: "" };
    }
    if (args.includes("pip")) {
      return { status: 0, stdout: "installed", stderr: "" };
    }
    if (args.includes("playwright") && args.includes("install")) {
      if (failChromium) {
        return { status: 1, stdout: "", stderr: "download failed" };
      }
      const executable = path.join(runOptions.env.PLAYWRIGHT_BROWSERS_PATH, "chromium-test", "chrome");
      fs.mkdirSync(path.dirname(executable), { recursive: true });
      fs.writeFileSync(executable, "chromium", "utf8");
      return { status: 0, stdout: "installed", stderr: "" };
    }
    const executable = path.join(runOptions.env.PLAYWRIGHT_BROWSERS_PATH, "chromium-test", "chrome");
    if (failFinalProbe && !command.includes(".python-stage-")) {
      return { status: 1, stdout: "", stderr: "final probe failed" };
    }
    return {
      status: fs.existsSync(executable) ? 0 : 1,
      stdout: `${JSON.stringify({
        python_version: "3.12.0",
        cos_version: "1.9.44",
        playwright_version: "1.62.0",
        chromium_executable: executable,
      })}\n`,
      stderr: "",
    };
  }
  const discover = () => ({ command: "base-python", args: [], version: [3, 12, 0] });
  const installed = ensurePythonRuntime({ ...options, run, discover });
  const markerBefore = fs.readFileSync(path.join(installed.root, "runtime.json"), "utf8");

  fs.appendFileSync(requirements, "# force replacement\n", "utf8");
  failChromium = true;
  assert.throws(
    () => ensurePythonRuntime({ ...options, run, discover }),
    /Could not install Fuploader Chromium: download failed/,
  );
  assert.equal(fs.readFileSync(path.join(installed.root, "runtime.json"), "utf8"), markerBefore);
  assert.ok(fs.existsSync(installed.python.chromiumExecutable));
  assert.deepEqual(
    fs.readdirSync(path.dirname(installed.root)).filter((name) => name.startsWith(".python-stage-")),
    [],
  );

  failChromium = false;
  failFinalProbe = true;
  assert.throws(
    () => ensurePythonRuntime({ ...options, run, discover }),
    /failed final validation/,
  );
  assert.equal(fs.readFileSync(path.join(installed.root, "runtime.json"), "utf8"), markerBefore);
  assert.ok(fs.existsSync(installed.python.chromiumExecutable));
  assert.deepEqual(
    fs.readdirSync(path.dirname(installed.root)).filter(
      (name) => name.startsWith(".python-stage-") || name.startsWith(".python-backup-"),
    ),
    [],
  );
});
