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
} from "../lib/python.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

test("discovers a supported local Python interpreter", () => {
  const python = discoverPython();
  assert.ok(python);
  assert.equal(python.version[0], 3);
  assert.ok(python.version[1] >= 9);
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
  function run(command, args) {
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
    return { status: 0, stdout: "3.12.0\n1.9.44\n", stderr: "" };
  }
  const discover = () => ({ command: "base-python", args: [], version: [3, 12, 0] });
  const installed = ensurePythonRuntime({ ...options, run, discover });
  assert.equal(installed.status, "installed");
  assert.equal(installed.root, pythonRuntimeRoot(options));
  assert.equal(installed.python.dependencyVersion, "1.9.44");
  const current = ensurePythonRuntime({ ...options, run, discover });
  assert.equal(current.status, "current");
  assert.equal(venvCreates, 1);
  const removed = removePythonRuntime(options);
  assert.equal(removed.status, "removed");
  assert.equal(fs.existsSync(installed.root), false);
});
