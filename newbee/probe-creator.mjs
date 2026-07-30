#!/usr/bin/env node

import {
  listAllCreatorContent,
  listCreatorContent,
} from "./creator-content.mjs";

function usage() {
  console.error(
    "Usage: node newbee/probe-creator.mjs <addon|wa|config|guide|all>",
  );
  process.exitCode = 2;
}

const command = process.argv[2] ?? "all";

try {
  if (command === "all") {
    console.log(JSON.stringify(await listAllCreatorContent(), null, 2));
  } else if (["addon", "wa", "config", "guide"].includes(command)) {
    console.log(JSON.stringify(await listCreatorContent(command), null, 2));
  } else {
    usage();
  }
} catch (error) {
  console.error(error?.message || String(error));
  process.exitCode = 1;
}
