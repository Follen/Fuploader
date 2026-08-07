import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const expectedVersion = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8")).version;
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "fupload-npm-install-"));
const npmCli = process.env.npm_execpath;
if (!npmCli) {
  throw new Error("npm_execpath is required. Run this check through npm run test:install.");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || packageRoot,
    encoding: "utf8",
    env: options.env || process.env,
    shell: false,
    windowsHide: true,
  });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed (${result.status}):\n${result.stdout}\n${result.stderr || result.error?.message || ""}`);
  }
  return result;
}

function runNpm(args, options = {}) {
  return run(process.execPath, [npmCli, ...args], options);
}

function installedCommand(prefix) {
  return process.platform === "win32"
    ? path.join(prefix, "fupload.cmd")
    : path.join(prefix, "bin", "fupload");
}

function installedPackage(prefix) {
  return process.platform === "win32"
    ? path.join(prefix, "node_modules", "@follenfang", "fupload")
    : path.join(prefix, "lib", "node_modules", "@follenfang", "fupload");
}

function runInstalled(prefix, args, options = {}) {
  const command = installedCommand(prefix);
  if (process.platform !== "win32") {
    return run(command, args, options);
  }
  return run(process.env.ComSpec || "cmd.exe", ["/d", "/c", command, ...args], options);
}

function hash(filename) {
  return crypto.createHash("sha256").update(fs.readFileSync(filename)).digest("hex");
}

async function exercise({ name, ignoreScripts }) {
  const prefix = path.join(temporary, `${name}-prefix`);
  const agentHome = path.join(temporary, `${name}-agent`);
  const stateRoot = path.join(temporary, `${name}-state`);
  const home = path.join(temporary, `${name}-home`);
  const customSkill = path.join(temporary, `${name}-custom-skill`);
  const project = path.join(temporary, `${name}-project`);
  const releaseRecord = path.join(project, "publish", "record", "01-plan.json");
  fs.mkdirSync(path.dirname(releaseRecord), { recursive: true });
  fs.writeFileSync(releaseRecord, '{"preserve":true}\n', "utf8");
  const beforeHash = hash(releaseRecord);
  const env = {
    ...process.env,
    FUPLOAD_AGENT_HOME: agentHome,
    HOME: home,
    USERPROFILE: home,
    LOCALAPPDATA: stateRoot,
    XDG_STATE_HOME: stateRoot,
  };
  const installArgs = ["install", "-g", "--prefix", prefix];
  if (ignoreScripts) {
    installArgs.push("--ignore-scripts");
  }
  installArgs.push(tarball);
  runNpm(installArgs, { env });

  const defaultSkill = path.join(agentHome, "skills", "fupload");
  const version = runInstalled(prefix, ["--skill-dir", customSkill, "--version"], { env, cwd: project });
  if (version.stdout.trim() !== expectedVersion) {
    throw new Error(`Unexpected CLI version: ${version.stdout}`);
  }
  if (!fs.existsSync(path.join(customSkill, ".fupload-npm-install.json"))) {
    throw new Error("The launcher did not install the custom Skill.");
  }
  if (!ignoreScripts && !fs.existsSync(path.join(defaultSkill, ".fupload-npm-install.json"))) {
    throw new Error("postinstall did not install the default Skill.");
  }
  const curseforgeConfig = path.join(home, ".fupload", "curseforge.env");
  if (!fs.existsSync(curseforgeConfig)) {
    throw new Error("The install/launcher flow did not create curseforge.env in the isolated home.");
  }
  const preservedConfig = "CURSEFORGE_AUTHOR_ID=42\nCURSEFORGE_API_KEY=keep\nCURSEFORGE_UPLOAD_TOKEN=keep\n";
  fs.writeFileSync(curseforgeConfig, preservedConfig, "utf8");
  const help = runInstalled(prefix, ["--skill-dir", customSkill, "--help"], { env, cwd: project });
  if (
    !help.stdout.includes("usage:") ||
    !help.stdout.includes("newbee") ||
    !help.stdout.includes("dd") ||
    !help.stdout.includes("fupload update") ||
    !help.stdout.includes("fupload uninstall")
  ) {
    throw new Error("The npm launcher did not invoke the Python CLI help.");
  }
  const runtimeRoot = path.join(
    stateRoot,
    process.platform === "win32" ? "Fupload" : "fupload",
    "python",
  );
  if (!fs.existsSync(runtimeRoot)) {
    throw new Error("The install/launcher flow did not create the managed Python runtime.");
  }

  const uninstall = runInstalled(prefix, ["--skill-dir", customSkill, "uninstall"], { env, cwd: project });
  const lines = uninstall.stdout.trim().split(/\r?\n/).filter(Boolean);
  const result = JSON.parse(lines.at(-1));
  if (!result.success) {
    throw new Error(`Self uninstall did not report success: ${uninstall.stdout}`);
  }
  if (
    fs.existsSync(installedCommand(prefix)) ||
    fs.existsSync(installedPackage(prefix)) ||
    fs.existsSync(defaultSkill) ||
    fs.existsSync(customSkill) ||
    fs.existsSync(path.join(stateRoot, process.platform === "win32" ? "Fupload" : "fupload"))
  ) {
    throw new Error(`Self uninstall left managed artifacts for ${name}.`);
  }
  if (hash(releaseRecord) !== beforeHash) {
    throw new Error("Self uninstall changed the project publish record.");
  }
  if (fs.readFileSync(curseforgeConfig, "utf8") !== preservedConfig) {
    throw new Error("Self uninstall did not preserve the CurseForge configuration.");
  }
}

const packDirectory = path.join(temporary, "pack");
fs.mkdirSync(packDirectory);
let tarball;
try {
  const pack = runNpm(["pack", "--json", "--ignore-scripts", "--pack-destination", packDirectory]);
  tarball = path.join(packDirectory, JSON.parse(pack.stdout)[0].filename);
  await exercise({ name: "normal", ignoreScripts: false });
  await exercise({ name: "ignore-scripts", ignoreScripts: true });
  process.stdout.write("Global install, managed Python runtime, Python launch, Skill, and self-uninstall checks passed.\n");
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
