import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const testRoot = path.join(packageRoot, "npm", "test");
const files = fs.readdirSync(testRoot)
  .filter((name) => name.endsWith(".test.mjs"))
  .sort()
  .map((name) => path.join(testRoot, name));
if (!files.length) {
  throw new Error("No Node test files were found.");
}
const result = spawnSync(process.execPath, ["--test", ...files], {
  cwd: packageRoot,
  stdio: "inherit",
  windowsHide: true,
});
if (result.error) {
  throw result.error;
}
process.exitCode = result.status ?? 1;
