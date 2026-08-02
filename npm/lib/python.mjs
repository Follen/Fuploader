import { spawnSync } from "node:child_process";

function probe(command, args, minimum) {
  const result = spawnSync(command, [...args, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"], {
    encoding: "utf8",
    shell: false,
    windowsHide: true,
  });
  if (result.status !== 0) {
    return null;
  }
  const match = result.stdout.trim().match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) {
    return null;
  }
  const version = match.slice(1).map(Number);
  if (version[0] !== 3 || version[1] < minimum) {
    return null;
  }
  return { command, args, version };
}

export function discoverPython({ platform = process.platform, minimumMinor = 9 } = {}) {
  const candidates = platform === "win32"
    ? [["python", []], ["py", ["-3"]], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [command, args] of candidates) {
    const result = probe(command, args, minimumMinor);
    if (result) {
      return result;
    }
  }
  return null;
}

export function runPython(python, script, args, options = {}) {
  return spawnSync(python.command, [...python.args, script, ...args], {
    cwd: options.cwd || process.cwd(),
    env: options.env || process.env,
    stdio: options.stdio || "inherit",
    encoding: options.encoding,
    shell: false,
    windowsHide: true,
  });
}
