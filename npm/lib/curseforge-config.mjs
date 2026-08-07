import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const CURSEFORGE_ENV_TEMPLATE = [
  "CURSEFORGE_AUTHOR_ID=",
  "CURSEFORGE_API_KEY=",
  "CURSEFORGE_UPLOAD_TOKEN=",
  "",
].join("\n");

export function curseForgeEnvPath({ home = os.homedir() } = {}) {
  return path.join(home, ".fupload", "curseforge.env");
}

export function ensureCurseForgeEnv({ home = os.homedir(), platform = process.platform } = {}) {
  const filename = curseForgeEnvPath({ home });
  fs.mkdirSync(path.dirname(filename), { recursive: true, mode: 0o700 });

  try {
    fs.writeFileSync(filename, CURSEFORGE_ENV_TEMPLATE, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
    if (platform !== "win32") {
      fs.chmodSync(filename, 0o600);
    }
    return { path: filename, status: "created" };
  } catch (error) {
    if (error?.code === "EEXIST") {
      return { path: filename, status: "preserved" };
    }
    throw error;
  }
}
