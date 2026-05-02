const API_PREFIX = "/api";
const TOKEN_KEY = "dwv2_tokens";

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
  const payload = text ? JSON.parse(text) : {};

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

  return parseResponse(response);
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
  const url = new URL("https://geocoding-api.open-meteo.com/v1/search");
  url.searchParams.set("name", city);
  url.searchParams.set("count", "1");
  url.searchParams.set("language", "ru");
  url.searchParams.set("format", "json");

  const response = await fetch(url);
  const payload = await parseResponse(response);
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
