import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { removeInstallTestDirectory, withInstallTestCleanup } from "../scripts/install-test-cleanup.mjs";

const target = path.join(os.tmpdir(), "fupload-npm-install-fixture");
const locked = () => Object.assign(new Error("EPERM during lstat of playwright/driver/node.exe"), { code: "EPERM", syscall: "lstat" });

test("retries the complete removal after transient Windows lstat failures", async () => {
  const calls = [];
  const waits = [];
  await removeInstallTestDirectory(target, {
    platform: "win32",
    remove: (directory, options) => {
      calls.push({ directory, options });
      if (calls.length < 3) throw locked();
    },
    wait: async (milliseconds) => waits.push(milliseconds),
  });
  assert.equal(calls.length, 3);
  assert.ok(calls.every((call) => call.directory === path.resolve(target)));
  assert.ok(calls.every((call) => call.options.recursive && call.options.force && call.options.maxRetries === 0));
  assert.deepEqual(waits, [250, 250]);
});

test("persistent Windows locks fail after a bounded number of retries", async () => {
  const failure = locked();
  let calls = 0;
  let waited = 0;
  await assert.rejects(removeInstallTestDirectory(target, {
    platform: "win32",
    remove: () => { calls += 1; throw failure; },
    wait: async (milliseconds) => { waited += milliseconds; },
  }), (error) => error === failure);
  assert.equal(calls, 21);
  assert.equal(waited, 5000);
});

test("non-transient errors and non-Windows failures are not retried", async () => {
  for (const [platform, code] of [["win32", "EINVAL"], ["linux", "EPERM"]]) {
    const failure = Object.assign(new Error("cannot remove"), { code });
    let calls = 0;
    await assert.rejects(removeInstallTestDirectory(target, {
      platform,
      remove: () => { calls += 1; throw failure; },
      wait: async () => assert.fail("unexpected retry"),
    }), (error) => error === failure);
    assert.equal(calls, 1);
  }
});

test("cleanup preserves the original check error and reports its own failure", async () => {
  const original = new Error("real uninstall verification failed");
  const cleanup = locked();
  const reported = [];
  await assert.rejects(withInstallTestCleanup(
    async () => { throw original; },
    async () => { throw cleanup; },
    { report: (error) => reported.push(error) },
  ), (error) => error === original);
  assert.deepEqual(reported, [cleanup]);
});

test("cleanup failure still fails a successful check", async () => {
  const failure = locked();
  let checked = false;
  await assert.rejects(withInstallTestCleanup(
    async () => { checked = true; },
    async () => { throw failure; },
  ), (error) => error === failure);
  assert.ok(checked);
});

test("cleanup removes only the allocated temporary directory", async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-npm-install-"));
  const neighbor = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-npm-install-"));
  t.after(() => fs.rmSync(neighbor, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, "nested"));
  fs.writeFileSync(path.join(root, "nested", "fixture"), "temporary");
  await removeInstallTestDirectory(root);
  assert.ok(!fs.existsSync(root));
  assert.ok(fs.existsSync(neighbor));
  for (const invalid of [os.tmpdir(), path.join(os.tmpdir(), "unrelated"), path.join(root, "fupload-npm-install-nested")]) {
    await assert.rejects(removeInstallTestDirectory(invalid, {
      remove: () => assert.fail("out-of-scope removal"),
    }), /outside this install test/);
  }
});
