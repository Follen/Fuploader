import { DEFAULT_API_BASE } from "./auth-state.mjs";
import { createCreatorSession, creatorHeaders } from "./creator-auth.mjs";

const CONTENT_TYPES = {
  addon: {
    endpoint: "/creator/wow/mod/publish_list",
    listKey: "list",
    totalKey: "total",
    params: {
      keyword: "",
      game_version_id: 0,
      sort_by: "t_last_update",
      sort_order: "DESC",
      pagenum: 1,
      pagesize: 100,
    },
  },
  wa: {
    endpoint: "/creator/wow/wa/mtg_uc_publish_list",
    listKey: "list",
    totalKey: "total",
    params: {
      keyword: "",
      game_version_id: 0,
      sort_by: "t_update_time",
      sort_order: "DESC",
      offset: 0,
      pagesize: 100,
    },
  },
  config: {
    endpoint: "/creator/wow/share_config/publish_list",
    listKey: "list",
    totalKey: "count",
    params: {
      keyword: "",
      game_version_id: 0,
      sort: 3,
      offset: 0,
      pagesize: 100,
    },
  },
  guide: {
    endpoint: "/creator/wow/guide/publish_list",
    listKey: "list",
    totalKey: "count",
    params: {
      article_type: 2,
      category_id: null,
      game_version_id: 0,
      keyword: "",
      sort_by: "date",
      tag: "",
      offset: 0,
      pagesize: 100,
    },
  },
};

function apiError(type, response, payload) {
  const detail = payload?.message || payload?.error || payload?.error_description;
  const apiCode = payload?.code != null ? `, apiCode=${payload.code}` : "";
  return new Error(
    `NewBeeBox ${type} list failed (${response.status}${apiCode})${detail ? `: ${detail}` : ""}`,
  );
}

function reviewLabel(visibility, value) {
  if (visibility === "private") return "not_submitted";
  return { 0: "reviewing", 1: "approved", 2: "rejected" }[value] ?? "unknown";
}

function firstValue(item, keys) {
  for (const key of keys) {
    if (item?.[key] !== undefined && item[key] !== null && item[key] !== "") {
      return item[key];
    }
  }
  return null;
}

async function postCreatorJson(fetchImpl, apiBase, session, endpoint, body) {
  const response = await fetchImpl(`${apiBase}${endpoint}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...creatorHeaders(session),
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  return { response, payload };
}

async function enrichAddonVersions(items, {
  apiBase,
  fetchImpl,
  session,
  concurrency = 4,
}) {
  let nextIndex = 0;
  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex++;
      const item = items[index];
      const { response, payload } = await postCreatorJson(
        fetchImpl,
        apiBase,
        session,
        "/creator/wow/mod_file/mod_file_list",
        {
          mod_id: Number(item.id),
          game_version_id: 0,
          pagenum: 1,
          pagesize: 1,
        },
      );
      if (!response.ok || payload?.code !== 1 || !payload?.data) {
        throw apiError("addon version", response, payload);
      }
      item.latestVersion = payload.data.list?.[0]?.t_display_name ?? null;
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, () => worker()),
  );
}

export function summarizeCreatorItem(type, item) {
  if (type === "addon") {
    const visibility = item.t_share === 0 ? "private" : "public";
    return {
      id: item.t_id ?? null,
      title: item.t_name ?? null,
      visibility,
      shareState: item.t_share ?? null,
      review: reviewLabel(visibility, item.t_check),
      reviewState: item.t_check ?? null,
      latestVersion: firstValue(item, [
        "t_version",
        "latest_version",
        "version_name",
        "version",
      ]),
    };
  }

  if (type === "wa") {
    const visibility = item.t_share_state === 2 ? "private" : "public";
    return {
      id: item.t_id ?? null,
      title: item.t_name ?? null,
      visibility,
      shareState: item.t_share_state ?? null,
      review: reviewLabel(visibility, item.t_check_status),
      reviewState: item.t_check_status ?? null,
      latestVersion: firstValue(item, ["t_version", "version"]),
    };
  }

  if (type === "config") {
    const visibility = item.t_sharing === 0 ? "private" : "public";
    return {
      id: item.t_id ?? null,
      title: item.t_title ?? null,
      visibility,
      shareState: item.t_sharing ?? null,
      review: reviewLabel(visibility, item.t_check),
      reviewState: item.t_check ?? null,
      latestVersion: firstValue(item, [
        "t_version",
        "latest_version",
        "version",
      ]),
    };
  }

  if (type === "guide") {
    const visibility = item.share_state === 0 ? "private" : "public";
    const reviewState = firstValue(item, [
      "check_status",
      "t_check",
      "review_status",
    ]);
    return {
      id: firstValue(item, ["t_id", "id"]),
      title: firstValue(item, ["t_name", "title"]),
      visibility,
      shareState: item.share_state ?? null,
      review: reviewLabel(visibility, reviewState),
      reviewState,
      latestVersion: null,
    };
  }

  throw new Error(`Unsupported NewBeeBox content type: ${type}`);
}

export async function listCreatorContent(type, {
  authDir,
  apiBase = DEFAULT_API_BASE,
  fetchImpl = fetch,
  session,
  params = {},
  includeAddonVersions = true,
} = {}) {
  const config = CONTENT_TYPES[type];
  if (!config) throw new Error(`Unsupported NewBeeBox content type: ${type}`);

  const activeSession =
    session ?? await createCreatorSession({ authDir, apiBase, fetchImpl });
  const { response, payload } = await postCreatorJson(
    fetchImpl,
    apiBase,
    activeSession,
    config.endpoint,
    { ...config.params, ...params },
  );
  if (!response.ok || payload?.code !== 1 || !payload?.data) {
    throw apiError(type, response, payload);
  }

  const items = Array.isArray(payload.data[config.listKey])
    ? payload.data[config.listKey]
    : [];
  const result = {
    type,
    total: Number(payload.data[config.totalKey] ?? items.length),
    items: items.map((item) => summarizeCreatorItem(type, item)),
  };
  if (type === "addon" && includeAddonVersions) {
    await enrichAddonVersions(result.items, {
      apiBase,
      fetchImpl,
      session: activeSession,
    });
  }
  return result;
}

export async function listAllCreatorContent(options = {}) {
  const apiBase = options.apiBase ?? DEFAULT_API_BASE;
  const fetchImpl = options.fetchImpl ?? fetch;
  const session = options.session ?? await createCreatorSession({
    authDir: options.authDir,
    apiBase,
    fetchImpl,
  });
  const shared = { ...options, apiBase, fetchImpl, session };
  return Promise.all(
    ["addon", "wa", "config", "guide"].map((type) =>
      listCreatorContent(type, shared)),
  );
}
