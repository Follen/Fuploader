import os from "node:os";
import path from "node:path";

import { ensureCurseForgeEnv } from "./curseforge-config.mjs";
import { readManagedInstall, recordManagedSkill } from "./managed-install.mjs";
import { resolveSkillDirectory } from "./options.mjs";
import { ensureSkill, loadDistribution } from "./skill-installer.mjs";
import { PACKAGE_NAME, inspectManagedSkill, resolveGlobalInstall, runNpmCli } from "./uninstall.mjs";

export class ManagedUpdateError extends Error {
  constructor(message, details) {
    super(message);
    this.name = "ManagedUpdateError";
    this.code = "FUPLOAD_UPDATE_FAILED";
    this.details = details;
  }
}

function bounded(value) {
  return String(value || "").trim().slice(0, 4000);
}

export async function updateSelf({
  packageRoot,
  target,
  platform = process.platform,
  env = process.env,
  home = os.homedir(),
  runNpm = runNpmCli,
} = {}) {
  const curseforgeConfig = ensureCurseForgeEnv({ home, platform });
  const installation = resolveGlobalInstall(packageRoot, platform);
  const current = loadDistribution(packageRoot);
  const primary = target || resolveSkillDirectory({ env, home });
  await ensureSkill({ packageRoot, target: primary });
  recordManagedSkill(primary, { platform, env, home });

  const args = ["install", "-g", "--ignore-scripts", "--prefix", installation.prefix, `${PACKAGE_NAME}@latest`];
  const npmResult = runNpm(args, { platform, env });
  if (npmResult.error || npmResult.status !== 0) {
    throw new ManagedUpdateError("npm could not update the Fuploader package and CLI.", {
      from_version: current.packageRecord.version,
      prefix: installation.prefix,
      exit_status: npmResult.status,
      stdout: bounded(npmResult.stdout),
      stderr: bounded(npmResult.stderr || npmResult.error?.message),
    });
  }

  let updated;
  try {
    updated = loadDistribution(packageRoot);
  } catch (error) {
    throw new ManagedUpdateError("The updated Fuploader package failed distribution validation.", {
      from_version: current.packageRecord.version,
      prefix: installation.prefix,
      reason: error.message,
    });
  }
  const registry = readManagedInstall({ platform, env, home });
  const targets = [
    ...new Set([
      ...registry.targets
        .filter((entry) => typeof entry?.path === "string")
        .map((entry) => path.resolve(entry.path)),
      path.resolve(resolveSkillDirectory({ env, home })),
      path.resolve(primary),
    ]),
  ];
  const skills = [];
  for (const candidate of targets) {
    const inspection = inspectManagedSkill(candidate);
    if (inspection.status === "preserved_unmanaged") {
      skills.push(inspection);
      continue;
    }
    try {
      const ensured = await ensureSkill({ packageRoot, target: candidate });
      recordManagedSkill(candidate, { platform, env, home });
      skills.push({ target: candidate, status: ensured.status, version: updated.packageRecord.version });
    } catch (error) {
      throw new ManagedUpdateError("The npm CLI updated but a managed Fuploader Skill could not be synchronized.", {
        from_version: current.packageRecord.version,
        to_version: updated.packageRecord.version,
        target: candidate,
        skills,
        reason: error.message,
      });
    }
  }
  return {
    schema: "fupload.npm-update-result.v1",
    success: true,
    package: PACKAGE_NAME,
    prefix: installation.prefix,
    from_version: current.packageRecord.version,
    to_version: updated.packageRecord.version,
    npm_exit_status: npmResult.status,
    curseforge_config: curseforgeConfig,
    skills,
  };
}
