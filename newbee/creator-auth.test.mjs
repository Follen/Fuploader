import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createCreatorSession } from "./creator-auth.mjs";

function jwt(payload) {
  return `${Buffer.from(JSON.stringify({ alg: "HS256" })).toString("base64url")}.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.signature`;
}

test("createCreatorSession supports exchange responses without jwtToken", async (t) => {
  const dir = await mkdtemp(join(tmpdir(), "fuploader-creator-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(
    join(dir, "access-token"),
    jwt({ exp: Math.floor(Date.now() / 1000) + 3600 }),
    "utf8",
  );

  const requests = [];
  const responses = [
    { code: 1, data: { code: "one-time-code" } },
    { code: 1, data: { token: "author-token" } },
    { code: 1, data: { resource_token: "resource-token" } },
  ];
  const fetchImpl = async (url, options) => {
    requests.push({ url, headers: options.headers, body: options.body });
    return new Response(JSON.stringify(responses.shift()), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const session = await createCreatorSession({ authDir: dir, fetchImpl });
  assert.deepEqual(session, {
    authorToken: "author-token",
    resourceToken: "resource-token",
  });
  assert.equal(requests.length, 3);
  assert.equal(requests[2].headers.token, "author-token");
  assert.equal("authorization" in requests[2].headers, false);
});

