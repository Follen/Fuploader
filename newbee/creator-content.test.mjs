import assert from "node:assert/strict";
import test from "node:test";

import {
  listAllCreatorContent,
  summarizeCreatorItem,
} from "./creator-content.mjs";

test("summarizeCreatorItem normalizes each creator content type", () => {
  assert.deepEqual(
    summarizeCreatorItem("addon", {
      t_id: 11,
      t_name: "Addon",
      t_share: 1,
      t_check: 0,
    }),
    {
      id: 11,
      title: "Addon",
      visibility: "public",
      shareState: 1,
      review: "reviewing",
      reviewState: 0,
      latestVersion: null,
    },
  );
  assert.equal(
    summarizeCreatorItem("wa", {
      t_id: 12,
      t_name: "WA",
      t_share_state: 2,
      t_check_status: 1,
      t_version: "1.2.3",
    }).review,
    "not_submitted",
  );
  assert.equal(
    summarizeCreatorItem("config", {
      t_id: 13,
      t_title: "Config",
      t_sharing: 1,
      t_check: 2,
    }).review,
    "rejected",
  );
  assert.equal(
    summarizeCreatorItem("guide", {
      id: 14,
      title: "Guide",
      share_state: 0,
    }).visibility,
    "private",
  );
});

test("listAllCreatorContent reuses one session and emits no credentials", async () => {
  const requests = [];
  const responses = {
    "/creator/wow/mod/publish_list": {
      code: 1,
      data: { list: [{ t_id: 1, t_name: "A", t_share: 0 }], total: 1 },
    },
    "/creator/wow/wa/mtg_uc_publish_list": {
      code: 1,
      data: {
        list: [{ t_id: 2, t_name: "W", t_share_state: 1, t_version: "2" }],
        total: 1,
      },
    },
    "/creator/wow/share_config/publish_list": {
      code: 1,
      data: { list: [{ t_id: 3, t_title: "C", t_sharing: 0 }], count: 1 },
    },
    "/creator/wow/guide/publish_list": {
      code: 1,
      data: { list: [{ id: 4, title: "G", share_state: 1 }], count: 1 },
    },
  };
  const fetchImpl = async (url, options) => {
    const path = new URL(url).pathname;
    requests.push({ path, options });
    const payload = path === "/creator/wow/mod_file/mod_file_list"
      ? { code: 1, data: { list: [{ t_display_name: "1.0.0" }], total: 1 } }
      : responses[path];
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const result = await listAllCreatorContent({
    apiBase: "https://example.test",
    fetchImpl,
    session: { authorToken: "author-secret", resourceToken: "resource-secret" },
  });

  assert.equal(requests.length, 5);
  assert.deepEqual(result.map((entry) => entry.type), [
    "addon",
    "wa",
    "config",
    "guide",
  ]);
  assert.equal(result[2].total, 1);
  assert.equal(result[0].items[0].latestVersion, "1.0.0");
  assert.equal(JSON.stringify(result).includes("author-secret"), false);
  assert.equal(JSON.stringify(result).includes("resource-secret"), false);
  assert.equal(requests[0].options.headers.token, "author-secret");
  const versionRequest = requests.find(
    (request) => request.path === "/creator/wow/mod_file/mod_file_list",
  );
  assert.equal(JSON.parse(versionRequest.options.body).mod_id, 1);
});
