const API_PREFIX = "/api";
const TOKEN_KEY = "dwv2_tokens";
const DEBUG_API = import.meta.env.DEV || localStorage.getItem("dwv2_debug_api") === "1";

function logApi(event, details = {}) {
  if (!DEBUG_API) return;
  console.info(`[dwv2:api] ${event}`, details);
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
    const message = payload.detail || payload.error || `HTTP ${response.status}`;
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
