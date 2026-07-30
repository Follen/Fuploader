import {
  DEFAULT_API_BASE,
  inspectAccessToken,
  readAuthState,
  refreshAuthState,
} from "./auth-state.mjs";

function apiError(operation, response, body) {
  const detail = body?.error_description || body?.message || body?.error;
  const apiCode = body?.code != null ? `, apiCode=${body.code}` : "";
  return new Error(
    `${operation} failed (${response.status}${apiCode})${detail ? `: ${detail}` : ""}`,
  );
}

async function postJson(fetchImpl, url, { body = {}, headers = {} } = {}) {
  const response = await fetchImpl(url, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  return { response, payload };
}

export async function ensureFreshDesktopAuth({
  authDir,
  fetchImpl = fetch,
  leewayMs = 30_000,
} = {}) {
  let state = await readAuthState(authDir);
  const metadata = inspectAccessToken(state.accessToken, Date.now() + leewayMs);
  if (!state.accessToken || metadata.expired !== false) {
    state = await refreshAuthState({ authDir, fetchImpl });
  }
  return state;
}

export async function createCreatorSession({
  authDir,
  apiBase = DEFAULT_API_BASE,
  fetchImpl = fetch,
} = {}) {
  const desktop = await ensureFreshDesktopAuth({ authDir, fetchImpl });

  const handoff = await postJson(fetchImpl, `${apiBase}/v3/user/auth2web`, {
    headers: {
      authorization: `Bearer ${desktop.accessToken}`,
      boxversion: "1.1.17",
      "accept-language": "zh-CN",
    },
  });
  if (
    !handoff.response.ok ||
    handoff.payload?.code !== 1 ||
    !handoff.payload?.data?.code
  ) {
    throw apiError("NewBeeBox auth2web", handoff.response, handoff.payload);
  }

  const exchange = await postJson(
    fetchImpl,
    `${apiBase}/v3/user/exchange_web_code`,
    {
      body: { code: handoff.payload.data.code },
      headers: { appid: "6", "accept-language": "zh-CN" },
    },
  );
  if (
    !exchange.response.ok ||
    exchange.payload?.code !== 1 ||
    !exchange.payload?.data?.token
  ) {
    throw apiError(
      "NewBeeBox exchange_web_code",
      exchange.response,
      exchange.payload,
    );
  }

  const authorToken = exchange.payload.data.token;
  const initialResourceToken = exchange.payload.data.jwtToken || null;
  const refreshHeaders = {
    appid: "6",
    token: authorToken,
    "accept-language": "zh-CN",
  };
  if (initialResourceToken) {
    refreshHeaders.authorization = `Bearer ${initialResourceToken}`;
  }
  const resourceRefresh = await postJson(
    fetchImpl,
    `${apiBase}/v3/user/refresh_web_resource_token`,
    {
      headers: refreshHeaders,
    },
  );
  if (
    !resourceRefresh.response.ok ||
    resourceRefresh.payload?.code !== 1 ||
    !resourceRefresh.payload?.data?.resource_token
  ) {
    throw apiError(
      "NewBeeBox refresh_web_resource_token",
      resourceRefresh.response,
      resourceRefresh.payload,
    );
  }

  return {
    authorToken,
    resourceToken: resourceRefresh.payload.data.resource_token,
  };
}

export function creatorHeaders(session) {
  return {
    appid: "6",
    authorization: `Bearer ${session.resourceToken}`,
    token: session.authorToken,
    "accept-language": "zh-CN",
  };
}

export async function checkCreatorSession(options = {}) {
  const apiBase = options.apiBase ?? DEFAULT_API_BASE;
  const fetchImpl = options.fetchImpl ?? fetch;
  const session = await createCreatorSession({ ...options, apiBase, fetchImpl });
  const result = await postJson(
    fetchImpl,
    `${apiBase}/v3/user/get_author_info`,
    { headers: creatorHeaders(session) },
  );
  return {
    ok: result.response.ok && result.payload?.code === 1,
    httpStatus: result.response.status,
    apiCode: result.payload?.code ?? null,
    verifyStatus: result.payload?.data?.result?.verify_status ?? null,
  };
}
