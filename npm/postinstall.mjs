import path from "node:path";
import { fileURLToPath } from "node:url";

import { ensureCurseForgeEnv } from "./lib/curseforge-config.mjs";
import { recordManagedSkill } from "./lib/managed-install.mjs";
import { resolveSkillDirectory } from "./lib/options.mjs";
import { ensureSkill } from "./lib/skill-installer.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = resolveSkillDirectory();

try {
  const config = ensureCurseForgeEnv();
  const result = await ensureSkill({ packageRoot, target });
  recordManagedSkill(target);
  process.stdout.write(`Fuploader Skill ${result.status}: ${target}\n`);
  process.stdout.write(`CurseForge configuration ${config.status}: ${config.path}\n`);
} catch (error) {
  process.stderr.write(`Fuploader Skill installation failed: ${error.message}\n`);
  process.exitCode = 1;
}
