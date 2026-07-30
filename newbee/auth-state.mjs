import { randomUUID } from "node:crypto";
import { hostname } from "node:os";
import { dirname, join } from "node:path";
import {
  mkdir,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";

export const DEFAULT_AUTH_BASE = "https://api.next.newbeebox.com/auth";
export const DEFAULT_API_BASE = "https://api.newbeebox.com";

const FILES = {
  accessToken: "access-token",
  refreshToken: "refresh-token",
  deviceProof: "device-proof",
};

export function defaultAuthDir(env = process.env) {
  if (!env.APPDATA) {
    throw new Error("APPDATA is not set; pass an explicit authDir instead");
  }
  return join(env.APPDATA, "NewBeeBox", "auth-store");
}

async function readOptionalText(path) {
  try {
    return (await readFile(path, "utf8")).trim() || null;
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

export async function readAuthState(authDir = defaultAuthDir()) {
  const entries = await Promise.all(
    Object.entries(FILES).map(async ([key, name]) => [
      key,
      await readOptionalText(join(authDir, name)),
    ]),
  );
  return Object.fromEntries(entries);
}

function decodeBase64UrlJson(value) {
  return JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
}

export function inspectAccessToken(token, now = Date.now()) {
  if (!token) return { present: false };

  const parts = token.split(".");
  const result = {
    present: true,
    characters: token.length,
    jwt: parts.length === 3,
  };
  if (parts.length !== 3) return result;

  try {
    const header = decodeBase64UrlJson(parts[0]);
    const payload = decodeBase64UrlJson(parts[1]);
    const expiresAt = Number.isFinite(Number(payload.exp))
      ? new Date(Number(payload.exp) * 1000)
      : null;
    return {
      ...result,
      algorithm: header.alg ?? null,
      issuer: payload.iss ?? null,
      clientId: payload.client_id ?? null,
      issuedAt: Number.isFinite(Number(payload.iat))
        ? new Date(Number(payload.iat) * 1000).toISOString()
        : null,
      expiresAt: expiresAt?.toISOString() ?? null,
      expired: expiresAt ? expiresAt.getTime() <= now : null,
    };
  } catch {
    return result;
  }
}

export function summarizeAuthState(state, now = Date.now()) {
  return {
    accessToken: inspectAccessToken(state.accessToken, now),
    refreshToken: {
      present: Boolean(state.refreshToken),
      characters: state.refreshToken?.length ?? 0,
    },
    deviceProof: {
      present: Boolean(state.deviceProof),
      characters: state.deviceProof?.length ?? 0,
    },
  };
}

async function writeAtomic(path, value) {
  await mkdir(dirname(path), { recursive: true });
  const tempPath = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(tempPath, value, "utf8");
    await rename(tempPath, path);
  } finally {
    await rm(tempPath, { force: true });
  }
}

export async function writeAuthState(updates, authDir = defaultAuthDir()) {
  const writes = Object.entries(updates)
    .filter(([key, value]) => FILES[key] && typeof value === "string" && value)
    .map(([key, value]) => writeAtomic(join(authDir, FILES[key]), value));
  await Promise.all(writes);
}

function authError(response, body) {
  const detail = body?.error_description || body?.message || body?.error;
  return new Error(
    `NewBeeBox refresh failed (${response.status})${detail ? `: ${detail}` : ""}`,
  );
}

export async function refreshAuthState({
  authDir = defaultAuthDir(),
  authBase = DEFAULT_AUTH_BASE,
  fetchImpl = fetch,
  deviceName = hostname(),
} = {}) {
  const current = await readAuthState(authDir);
  if (!current.refreshToken) {
    throw new Error("NewBeeBox refresh-token is missing");
  }

  const form = new URLSearchParams({
    client_id: "nbb-desktop",
    grant_type: "refresh_token",
    refresh_token: current.refreshToken,
    device_name: deviceName,
    device_type: "desktop",
  });
  if (current.deviceProof) form.set("device_proof", current.deviceProof);

  const response = await fetchImpl(`${authBase}/connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: form,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.access_token) throw authError(response, body);

  const next = {
    accessToken: body.access_token,
    refreshToken: body.refresh_token || current.refreshToken,
    deviceProof: body.device_proof || current.deviceProof,
  };
  await writeAuthState(next, authDir);
  return next;
}

export async function checkAccessToken({
  authDir = defaultAuthDir(),
  apiBase = DEFAULT_API_BASE,
  fetchImpl = fetch,
} = {}) {
  const state = await readAuthState(authDir);
  if (!state.accessToken) return { ok: false, reason: "missing_access_token" };

  const response = await fetchImpl(`${apiBase}/user/info`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${state.accessToken}`,
      "content-type": "application/json",
    },
    body: "{}",
  });
  const body = await response.json().catch(() => null);
  return {
    ok: response.ok && body?.code === 1,
    httpStatus: response.status,
    apiCode: body?.code ?? null,
    message: body?.message ?? null,
  };
}

