const API_PREFIX = "/api";
const TOKEN_KEY = "dwv2_tokens";
const DEBUG_API = import.meta.env.DEV || localStorage.getItem("dwv2_debug_api") === "1";

function logApi(event, details = {}) {
  if (!DEBUG_API) return;
  console.info(`[dwv2:api] ${event}`, details);
}

function formatApiError(payload, fallback) {
  if (!payload || typeof payload !== "object") return fallback;
  if (payload.detail) return String(payload.detail);
  if (payload.error) return String(payload.error);

  const messages = Object.entries(payload)
    .flatMap(([field, value]) => {
      const values = Array.isArray(value) ? value : [value];
      return values.map((item) => `${field}: ${String(item)}`);
    })
    .filter(Boolean);

  return messages.length ? messages.join("; ") : fallback;
}

export function readTokens() {
  try {
    return JSON.parse(localStorage.getItem(TOKEN_KEY)) || null;
  } catch {
    return null;
  }
}

export function saveTokens(tokens) {
  localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
}

async function parseResponse(response) {
  const text = await response.text();
  let payload = {};

  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    console.error("[dwv2:api] response_json_parse_failed", {
      status: response.status,
      url: response.url,
      bodyPreview: text.slice(0, 300),
    });
    throw error;
  }

  if (!response.ok) {
    const message = formatApiError(payload, `HTTP ${response.status}`);
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

export async function apiRequest(path, options = {}, tokens = null) {
  const method = options.method || "GET";
  logApi("request_started", { method, path, authenticated: Boolean(tokens?.access) });

  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (tokens?.access) {
    headers.Authorization = `Bearer ${tokens.access}`;
  }

  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers,
  });

  const payload = await parseResponse(response);
  logApi("request_finished", {
    method,
    path,
    status: response.status,
    keys: Object.keys(payload),
  });
  return payload;
}

export async function login(username, password) {
  return apiRequest("/auth/login/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function verifyTelegramLogin(challengeId, code) {
  return apiRequest("/auth/telegram/2fa/login/verify/", {
    method: "POST",
    body: JSON.stringify({ challenge_id: challengeId, code }),
  });
}

export async function signup(username, email, password) {
  return apiRequest("/auth/signup/", {
    method: "POST",
    body: JSON.stringify({ username, email, password }),
  });
}

export async function refreshAccess(refresh) {
  return apiRequest("/auth/token/refresh/", {
    method: "POST",
    body: JSON.stringify({ refresh }),
  });
}

export function getProfile(tokens) {
  return apiRequest("/auth/profile/", {}, tokens);
}

export function updateProfile(payload, tokens) {
  return apiRequest("/auth/profile/", {
    method: "PATCH",
    body: JSON.stringify(payload),
  }, tokens);
}

export function deleteProfile(tokens) {
  return apiRequest("/auth/profile/", { method: "DELETE" }, tokens);
}

export function changePassword(payload, tokens) {
  return apiRequest("/auth/password/change/", {
    method: "POST",
    body: JSON.stringify(payload),
  }, tokens);
}

export function getTelegram2FA(tokens) {
  return apiRequest("/auth/telegram/2fa/", {}, tokens);
}

export function updateTelegram2FASettings(payload, tokens) {
  return apiRequest("/auth/telegram/2fa/", {
    method: "PATCH",
    body: JSON.stringify(payload),
  }, tokens);
}

export function startTelegram2FASetup(telegramUsername, tokens) {
  return apiRequest("/auth/telegram/2fa/setup/start/", {
    method: "POST",
    body: JSON.stringify({ telegram_username: telegramUsername }),
  }, tokens);
}

export function verifyTelegram2FASetup(code, tokens) {
  return apiRequest("/auth/telegram/2fa/setup/verify/", {
    method: "POST",
    body: JSON.stringify({ code }),
  }, tokens);
}

export async function geocodeCity(city) {
  const payload = await apiRequest(`/geocode?city=${encodeURIComponent(city)}&limit=1`);
  const place = payload.results?.[0];

  if (!place) {
    throw new Error("Город не найден");
  }

  return {
    city: [place.name, place.country].filter(Boolean).join(", "),
    latitude: place.latitude,
    longitude: place.longitude,
  };
}

export function listProviderApplications(tokens) {
  return apiRequest("/provider-applications/", {}, tokens);
}

export function createProviderApplication(payload, tokens) {
  return apiRequest("/provider-applications/", {
    method: "POST",
    body: JSON.stringify(payload),
  }, tokens);
}

export function listAdminDwdApplications(tokens) {
  return apiRequest("/admin/dwd/applications/", {}, tokens);
}

export function getAdminDwdApplication(id, tokens) {
  return apiRequest(`/admin/dwd/applications/${id}/`, {}, tokens);
}

export function updateAdminDwdApplication(id, payload, tokens) {
  return apiRequest(`/admin/dwd/applications/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }, tokens);
}

export function approveDwdApplication(id, tokens) {
  return apiRequest(`/admin/dwd/applications/${id}/approve/`, { method: "POST" }, tokens);
}

export function rejectDwdApplication(id, tokens) {
  return apiRequest(`/admin/dwd/applications/${id}/reject/`, { method: "POST" }, tokens);
}

export function listAdminDwdDevices(tokens) {
  return apiRequest("/admin/dwd/devices/", {}, tokens);
}

export function getAdminDwdDevice(id, tokens) {
  return apiRequest(`/admin/dwd/devices/${id}/`, {}, tokens);
}

export function updateAdminDwdDevice(id, payload, tokens) {
  return apiRequest(`/admin/dwd/devices/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }, tokens);
}

export function runAdminDwdDeviceAction(id, action, tokens) {
  return apiRequest(`/admin/dwd/devices/${id}/action/`, {
    method: "POST",
    body: JSON.stringify({ action }),
  }, tokens);
}

export function listAdminDwdDeviceEvents(tokens, params = {}) {
  const query = new URLSearchParams(params).toString();
  return apiRequest(`/admin/dwd/device-events/${query ? `?${query}` : ""}`, {}, tokens);
}

export function listAdminDwdUsers(tokens) {
  return apiRequest("/admin/dwd/users/", {}, tokens);
}

export function updateAdminDwdUserRole(id, role, tokens) {
  return apiRequest(`/admin/dwd/users/${id}/role/`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  }, tokens);
}

export function deleteAdminDwdUser(id, tokens) {
  return apiRequest(`/admin/dwd/users/${id}/`, { method: "DELETE" }, tokens);
}

export function getProviderDashboard(tokens) {
  return apiRequest("/provider-dashboard/", {}, tokens);
}

export function listAdminDwdProvisioning(tokens) {
  return apiRequest("/admin/dwd/provisioning/", {}, tokens);
}

export function createDwdProvisioning(payload, tokens) {
  return apiRequest("/admin/dwd/provisioning/", {
    method: "POST",
    body: JSON.stringify(payload),
  }, tokens);
}

export function markDwdProvisioningSent(id, tokens) {
  return apiRequest(`/admin/dwd/provisioning/${id}/mark-sent/`, { method: "POST" }, tokens);
}
