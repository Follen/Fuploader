import os from "node:os";
import path from "node:path";

export function resolveSkillDirectory({ explicit, env = process.env, home } = {}) {
  if (explicit) {
    return path.resolve(explicit);
  }
  if (env.FUPLOAD_AGENT_HOME) {
    return path.resolve(env.FUPLOAD_AGENT_HOME, "skills", "fupload");
  }
  return path.join(home || os.homedir(), ".agents", "skills", "fupload");
}

export function parseLauncherOptions(argv) {
  const forwarded = [];
  let skillDirectory;
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--skill-dir") {
      const candidate = argv[index + 1];
      if (!candidate || candidate.startsWith("--")) {
        throw new Error("--skill-dir requires a directory path.");
      }
      skillDirectory = candidate;
      index += 1;
      continue;
    }
    if (value.startsWith("--skill-dir=")) {
      skillDirectory = value.slice("--skill-dir=".length);
      if (!skillDirectory) {
        throw new Error("--skill-dir requires a directory path.");
      }
      continue;
    }
    forwarded.push(value);
  }
  return { forwarded, skillDirectory };
}
