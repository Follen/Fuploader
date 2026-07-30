import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  inspectAccessToken,
  readAuthState,
  refreshAuthState,
} from "./auth-state.mjs";

function jwt(payload) {
  const header = Buffer.from(JSON.stringify({ alg: "HS256" })).toString(
    "base64url",
  );
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${header}.${body}.signature`;
}

test("inspectAccessToken reports expiry without exposing the token", () => {
  const token = jwt({ exp: 100, iat: 10, client_id: "nbb-desktop" });
  const result = inspectAccessToken(token, 101_000);
  assert.equal(result.expired, true);
  assert.equal(result.clientId, "nbb-desktop");
  assert.equal(JSON.stringify(result).includes(token), false);
});

test("refreshAuthState preserves refresh token and device proof", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "fuploader-auth-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(join(dir, "refresh-token"), "refresh-old", "utf8");
  await writeFile(join(dir, "device-proof"), "proof-old", "utf8");

  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, body: String(options.body) });
    return new Response(JSON.stringify({ access_token: "access-new" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  const state = await refreshAuthState({
    authDir: dir,
    fetchImpl,
    deviceName: "test-host",
  });

  assert.deepEqual(state, {
    accessToken: "access-new",
    refreshToken: "refresh-old",
    deviceProof: "proof-old",
  });
  assert.match(requests[0].body, /client_id=nbb-desktop/);
  assert.match(requests[0].body, /device_proof=proof-old/);
  assert.equal(await readFile(join(dir, "access-token"), "utf8"), "access-new");
  assert.deepEqual(await readAuthState(dir), state);
});

