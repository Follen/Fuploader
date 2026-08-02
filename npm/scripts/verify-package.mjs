import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const npmCli = process.env.npm_execpath;
if (!npmCli) {
  throw new Error("npm_execpath is required. Run this check through npm run test:pack.");
}
const result = spawnSync(process.execPath, [npmCli, "pack", "--dry-run", "--json", "--ignore-scripts"], {
  cwd: packageRoot,
  encoding: "utf8",
  shell: false,
  windowsHide: true,
});
if (result.status !== 0) {
  process.stderr.write(result.stderr || result.stdout || result.error?.message || "npm pack failed.\n");
  process.exit(result.status || 1);
}
const records = JSON.parse(result.stdout);
const files = records[0]?.files?.map((entry) => entry.path).sort() || [];
const allowed = ["README.md", "package.json", "npm/bin/", "npm/lib/", "npm/postinstall.mjs", "npm/skill-manifest.json", "fupload/SKILL.md", "fupload/agents/", "fupload/examples/", "fupload/references/", "fupload/scripts/"];
const forbidden = [
  /(^|\/)analyze\//i,
  /(^|\/)publish\//i,
  /(^|\/)docs\/comet\//i,
  /(^|\/)auth-store\//i,
  /__pycache__/i,
  /\.pyc$/i,
  /(^|\/)tests?\//i,
  /(^|\/)\.env$/i,
];
for (const file of files) {
  if (!allowed.some((prefix) => file === prefix || file.startsWith(prefix))) {
    throw new Error(`Unexpected package file: ${file}`);
  }
  if (forbidden.some((pattern) => pattern.test(file))) {
    throw new Error(`Forbidden package file: ${file}`);
  }
}
for (const required of [
  "package.json",
  "npm/bin/fupload.mjs",
  "npm/lib/uninstall.mjs",
  "npm/skill-manifest.json",
  "fupload/SKILL.md",
  "fupload/scripts/fupload.py",
]) {
  if (!files.includes(required)) {
    throw new Error(`Required package file is missing: ${required}`);
  }
}
const secretPatterns = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/,
  /\bAKIA[0-9A-Z]{16}\b/,
  /\bnpm_[A-Za-z0-9]{20,}\b/,
  /\bncc_[A-Za-z0-9]{20,}\b/,
];
for (const file of files) {
  const absolute = path.join(packageRoot, ...file.split("/"));
  if (!fs.existsSync(absolute) || fs.statSync(absolute).size > 2_000_000) {
    continue;
  }
  const content = fs.readFileSync(absolute, "utf8");
  if (secretPatterns.some((pattern) => pattern.test(content))) {
    throw new Error(`Credential-like content found in package file: ${file}`);
  }
}
process.stdout.write(`Package inventory verified: ${files.length} files, ${records[0].size} bytes packed.\n`);
