import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const transientWindowsErrors = new Set(["EBUSY", "EMFILE", "ENFILE", "ENOTEMPTY", "EPERM", "EACCES"]);

export async function removeInstallTestDirectory(directory, {
  temporaryRoot = os.tmpdir(),
  platform = process.platform,
  remove = fs.rmSync,
  wait = delay,
} = {}) {
  const target = path.resolve(directory);
  const parent = path.resolve(temporaryRoot);
  if (path.dirname(target) !== parent || !/^fupload-npm-install-.+$/u.test(path.basename(target))) {
    throw new Error("Refusing to remove a directory outside this install test's temporary scope.");
  }
  // Node 20's synchronous rimraf can throw from lstat before its built-in
  // retry loop. Retry the whole operation, for at most five seconds of waits.
  const retries = platform === "win32" ? 20 : 0;
  for (let attempt = 0; ; attempt += 1) {
    try {
      remove(target, { recursive: true, force: true, maxRetries: 0 });
      return;
    } catch (error) {
      if (attempt >= retries || !transientWindowsErrors.has(error.code)) {
        throw error;
      }
      await wait(250);
    }
  }
}

export async function withInstallTestCleanup(check, cleanup, {
  report = (error) => console.error("Install-test temporary cleanup also failed:", error),
} = {}) {
  let checkFailed = false;
  try {
    return await check();
  } catch (error) {
    checkFailed = true;
    throw error;
  } finally {
    try {
      await cleanup();
    } catch (error) {
      if (!checkFailed) {
        throw error;
      }
      // Keep the original installation/uninstallation failure as the thrown
      // error, even when reporting the secondary cleanup failure fails.
      try { report(error); } catch {}
    }
  }
}
