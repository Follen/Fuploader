import path from "node:path";
import { fileURLToPath } from "node:url";

import { ensureCurseForgeEnv } from "./lib/curseforge-config.mjs";
import { recordManagedSkill } from "./lib/managed-install.mjs";
import { resolveSkillDirectory } from "./lib/options.mjs";
import { ensurePythonRuntime } from "./lib/python.mjs";
import { ensureSkill } from "./lib/skill-installer.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = resolveSkillDirectory();

try {
  const config = ensureCurseForgeEnv();
  const runtime = ensurePythonRuntime({ packageRoot });
  const result = await ensureSkill({ packageRoot, target });
  recordManagedSkill(target);
  process.stdout.write(`Fuploader Skill ${result.status}: ${target}\n`);
  process.stdout.write(`CurseForge configuration ${config.status}: ${config.path}\n`);
  process.stdout.write(`Python runtime ${runtime.status}: ${runtime.root}\n`);
} catch (error) {
  process.stderr.write(`Fuploader installation failed: ${error.message}\n`);
  process.exitCode = 1;
}
