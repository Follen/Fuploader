import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  discoverPython,
  discoverUv,
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

test("discovers uv and rejects invalid version output", () => {
  let invocation;
  const found = discoverUv({
    run(command, args, options) {
      invocation = { command, args, options };
      return { status: 0, stdout: "uv 0.12.1 (build metadata)\n" };
    },
  });
  assert.deepEqual(found, { command: "uv", args: [], version: [0, 12, 1] });
  assert.equal(invocation.command, "uv");
  assert.deepEqual(invocation.args, ["--version"]);
  assert.equal(invocation.options.shell, false);
  assert.equal(invocation.options.windowsHide, true);
  assert.equal(discoverUv({ run: () => ({ status: 0, stdout: "unexpected\n" }) }), null);
  assert.equal(discoverUv({ run: () => ({ status: 1, stdout: "" }) }), null);
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
  let uvInstalls = 0;
  let chromiumInstalls = 0;
  const stagingRoots = [];
  function run(command, args, runOptions = {}) {
    if (args.includes("venv")) {
      const staging = args.at(-1);
      stagingRoots.push(staging);
      fs.mkdirSync(path.dirname(pythonRuntimeExecutable(staging, "linux")), { recursive: true });
      fs.writeFileSync(pythonRuntimeExecutable(staging, "linux"), "python", "utf8");
      venvCreates += 1;
      return { status: 0, stdout: "", stderr: "" };
    }
    if (command === "managed-uv") {
      assert.deepEqual(args, [
        "pip", "install",
        "--python", pythonRuntimeExecutable(stagingRoots.at(-1), "linux"),
        "--requirements", path.join(packageRoot, "npm", "lib", "python-requirements.txt"),
        "--link-mode", "copy",
        "--no-config",
        "--no-progress",
        "--no-python-downloads",
      ]);
      uvInstalls += 1;
      return { status: 0, stdout: "installed", stderr: "" };
    }
    if (args.includes("pip")) {
      assert.fail("pip fallback was used while uv was available");
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
  const locateUv = () => ({ command: "managed-uv", args: [], version: [0, 12, 1] });
  const installed = ensurePythonRuntime({ ...options, run, discover, discoverUv: locateUv });
  assert.equal(installed.status, "installed");
  assert.equal(installed.root, pythonRuntimeRoot(options));
  assert.equal(installed.python.dependencyVersion, "1.9.44");
  assert.equal(installed.python.playwrightVersion, "1.62.0");
  assert.ok(fs.existsSync(installed.python.chromiumExecutable));
  const marker = JSON.parse(fs.readFileSync(path.join(installed.root, "runtime.json"), "utf8"));
  assert.equal(marker.dependency_installer, "uv");
  assert.equal(marker.dependency_installer_version, "0.12.1");
  const current = ensurePythonRuntime({ ...options, run, discover, discoverUv: () => null });
  assert.equal(current.status, "current");
  assert.equal(venvCreates, 1);
  assert.equal(uvInstalls, 1);
  assert.equal(chromiumInstalls, 1);
  fs.rmSync(installed.python.chromiumExecutable);
  const repaired = ensurePythonRuntime({ ...options, run, discover, discoverUv: locateUv });
  assert.equal(repaired.status, "installed");
  assert.ok(fs.existsSync(repaired.python.chromiumExecutable));
  assert.equal(venvCreates, 2);
  assert.equal(uvInstalls, 2);
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
  const withoutUv = () => null;
  const installed = ensurePythonRuntime({ ...options, run, discover, discoverUv: withoutUv });
  const markerBefore = fs.readFileSync(path.join(installed.root, "runtime.json"), "utf8");
  assert.equal(JSON.parse(markerBefore).dependency_installer, "pip");

  fs.appendFileSync(requirements, "# force replacement\n", "utf8");
  failChromium = true;
  assert.throws(
    () => ensurePythonRuntime({ ...options, run, discover, discoverUv: withoutUv }),
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
    () => ensurePythonRuntime({ ...options, run, discover, discoverUv: withoutUv }),
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
