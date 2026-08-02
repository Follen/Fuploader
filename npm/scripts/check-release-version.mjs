import path from "node:path";
import { fileURLToPath } from "node:url";

import { assertUnifiedVersions, readVersions } from "../lib/versions.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const version = assertUnifiedVersions(readVersions(packageRoot));
const requireTag = process.argv.includes("--require-tag");
const explicit = process.argv.find((value) => /^v\d/.test(value));
const tag = process.env.GITHUB_REF_NAME || explicit || "";
if (requireTag || tag) {
  if (tag !== `v${version}`) {
    throw new Error(`Release tag ${tag || "<missing>"} does not match v${version}.`);
  }
}
process.stdout.write(`Fuploader version ${version} is consistent${tag ? ` with ${tag}` : ""}.\n`);
