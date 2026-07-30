#!/usr/bin/env node

import {
  checkAccessToken,
  readAuthState,
  refreshAuthState,
  summarizeAuthState,
} from "./auth-state.mjs";
import { checkCreatorSession } from "./creator-auth.mjs";

function usage() {
  console.error(
    "Usage: node newbee/probe-auth.mjs <status|check|refresh|creator-check>",
  );
  process.exitCode = 2;
}

const command = process.argv[2] ?? "status";

try {
  if (command === "status") {
    const state = await readAuthState();
    console.log(JSON.stringify(summarizeAuthState(state), null, 2));
  } else if (command === "check") {
    console.log(JSON.stringify(await checkAccessToken(), null, 2));
  } else if (command === "refresh") {
    const state = await refreshAuthState();
    console.log(JSON.stringify(summarizeAuthState(state), null, 2));
  } else if (command === "creator-check") {
    console.log(JSON.stringify(await checkCreatorSession(), null, 2));
  } else {
    usage();
  }
} catch (error) {
  console.error(error?.message || String(error));
  process.exitCode = 1;
}
