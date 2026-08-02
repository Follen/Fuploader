import fs from "node:fs";
import path from "node:path";

function readJson(filename) {
  return JSON.parse(fs.readFileSync(filename, "utf8"));
}

function matchedVersion(filename, pattern, label) {
  const source = fs.readFileSync(filename, "utf8");
  const match = source.match(pattern);
  if (!match) {
    throw new Error(`${label} version could not be read from ${filename}.`);
  }
  return match[1];
}

export function readVersions(packageRoot, { includeManifest = true } = {}) {
  const packageRecord = readJson(path.join(packageRoot, "package.json"));
  const skillFile = path.join(packageRoot, "fupload", "SKILL.md");
  const frontmatter = fs.readFileSync(skillFile, "utf8").split(/^---\s*$/m)[1] || "";
  const skillMatch = frontmatter.match(/^\s*version:\s*["']?([^\s"']+)["']?\s*$/m);
  if (!skillMatch) {
    throw new Error(`Skill metadata version could not be read from ${skillFile}.`);
  }
  const versions = {
    package: packageRecord.version,
    skill: skillMatch[1],
    python: matchedVersion(
      path.join(packageRoot, "fupload", "scripts", "fupload_cli", "__init__.py"),
      /__version__\s*=\s*["']([^"']+)["']/,
      "Python CLI",
    ),
  };
  const lockFile = path.join(packageRoot, "package-lock.json");
  if (fs.existsSync(lockFile)) {
    const lock = readJson(lockFile);
    versions.lock = lock.version;
    versions.lockRoot = lock.packages?.[""]?.version;
  }
  const manifestFile = path.join(packageRoot, "npm", "skill-manifest.json");
  if (includeManifest && fs.existsSync(manifestFile)) {
    const manifest = readJson(manifestFile);
    versions.manifestPackage = manifest.package_version;
    versions.manifestSkill = manifest.skill_version;
  }
  return versions;
}

export function assertUnifiedVersions(versions) {
  const expected = versions.package;
  const mismatches = Object.entries(versions).filter(([, value]) => value !== expected);
  if (mismatches.length) {
    throw new Error(
      `Version mismatch: expected ${expected}; ${mismatches.map(([name, value]) => `${name}=${value}`).join(", ")}.`,
    );
  }
  return expected;
}
