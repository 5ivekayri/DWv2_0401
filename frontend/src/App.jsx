import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bell,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  CloudSun,
  Copy,
  Cpu,
  Droplets,
  ExternalLink,
  FileText,
  Lock,
  LogIn,
  LogOut,
  MapPin,
  MessageCircle,
  Moon,
  Radio,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  Terminal,
  Thermometer,
  UserCircle,
  UserPlus,
  Waves,
  Wind,
} from "lucide-react";
import {
  approveDwdApplication,
  apiRequest,
  changePassword,
  clearTokens,
  createDwdProvisioning,
  createProviderApplication,
  createSupportTicket,
  deleteAdminDwdUser,
  deleteProfile,
  geocodeCity,
  getExtendedWeather,
  getAdminIotConfig,
  getAdminIotStatus,
  getProviderDashboard,
  getProfile,
  generateProviderFirmware,
  listAdminDwdDeviceEvents,
  listAdminDwdApplications,
  listAdminDwdDevices,
  listAdminDwdProvisioning,
  listAdminDwdUsers,
  listAdminAiOutfitRecommendations,
  listDwdApplicationMessages,
  listDwdNotifications,
  listStationRequests,
  listSupportTicketMessages,
  listSupportTickets,
  listProviderApplications,
  login,
  markDwdProvisioningSent,
  markDwdNotificationRead,
  readTokens,
  regenerateAdminAiOutfitRecommendation,
  rejectDwdApplication,
  runAdminDwdDeviceAction,
  saveTokens,
  sendDwdApplicationMessage,
  sendSupportTicketMessage,
  signup,
  startTelegram2FASetup,
  updateTelegram2FASettings,
  updateAdminDwdApplication,
  updateAdminDwdDevice,
  updateAdminIotConfig,
  updateAdminDwdUserRole,
  updateProfile,
  updateSupportTicket,
  verifyTelegram2FASetup,
  verifyTelegramLogin,
} from "./api";

const DEFAULT_COORDS = {
  city: "Москва",
  lat: "55.7512",
  lon: "37.6184",
};

const THEME_KEY = "dwv2_theme";
const DEBUG_UI = import.meta.env.DEV || localStorage.getItem("dwv2_debug_ui") === "1";
const DEFAULT_DWD_FORM = { city: "", email: "", comment: "" };
const DEFAULT_PROFILE_FORM = { username: "", email: "" };
const DEFAULT_PASSWORD_FORM = { current_password: "", new_password: "" };
const DEFAULT_SUPPORT_FORM = { subject: "", category: "service", message: "" };
const DEFAULT_TELEGRAM_2FA_FORM = {
  telegram_username: "",
  code: "",
  frequency: "week",
  is_enabled: false,
  is_linked: false,
  telegram_bot_url: "https://t.me/darkweather_2fa_bot",
  telegram_bot_username: "@darkweather_2fa_bot",
};
const DEFAULT_LOGIN_2FA_FORM = { code: "" };
const FIRMWARE_TEMPLATES = {
  serial_bridge:
    "1. Откройте Arduino IDE.\n2. Вставьте код прошивки serial_bridge.\n3. Выберите плату и serial-порт.\n4. Нажмите Upload.\n5. Подключите плату к bridge-хосту и проверьте телеметрию в Dark Weather.",
  esp01_wifi:
    "1. Откройте Arduino IDE.\n2. Вставьте код прошивки ESP-01 Wi-Fi.\n3. Укажите Wi-Fi credentials и настройки устройства Dark Weather.\n4. Выберите плату ESP-01 и режим загрузки.\n5. Загрузите прошивку и проверьте телеметрию в Dark Weather.",
  ethernet_shield:
    "1. Откройте Arduino IDE и вставьте код прошивки Ethernet Shield.\n2. Проверьте сетевые настройки.\n3. Выберите плату Arduino.\n4. Загрузите прошивку.\n5. Подключите Ethernet и проверьте телеметрию в Dark Weather.",
};
const DEFAULT_PROVISIONING_FORM = {
  application_id: "",
  user_id: "",
  device_id: "",
  firmware_type: "esp01_wifi",
  firmware_version: "1.0.0",
  instruction_text: "",
  wifi_ssid: "",
  wifi_password: "",
  delivery_channel: "email",
  notes: "",
};
const DEFAULT_PROVIDER_FIRMWARE_FORM = {
  device_id: "",
  firmware_type: "esp01_wifi",
  firmware_version: "1.0.0",
  wifi_ssid: "",
  wifi_password: "",
};
const DEFAULT_IOT_CONFIG_FORM = {
  connection_mode: "wifi_esp01",
  serial_port: "COM3",
  baud_rate: 9600,
  linked_device_id: "",
  enabled: false,
  mqtt_enabled: false,
  mqtt_host: "127.0.0.1",
  mqtt_port: 1883,
  mqtt_topic: "weather/station",
  mqtt_username: "",
  mqtt_password: "",
};

function logUi(event, details = {}) {
  if (!DEBUG_UI) return;
  console.info(`[dwv2:ui] ${event}`, details);
}

function getInitialTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function cleanRecommendationText(value) {
  if (!value) return "";
  const cleaned = String(value)
    .replace(/<\/?assistant>/gi, "")
    .replace(/<\/?user>/gi, "")
    .replace(/<\/?system>/gi, "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(assistant|user|system|developer)\s*:\s*/i, "").trim())
    .filter((line) => line && !/^(user\s+safety|system\s+safety|assistant\s+safety|safety|policy|metadata|status|analysis|confidence)\s*:?/i.test(line))
    .filter((line) => !/^(safe|unsafe|ok)$/i.test(line))
    .join(" ")
    .replace(/\s{2,}/g, " ")
    .trim();

  if (!cleaned || /^(safe|unsafe|user safety: safe)$/i.test(cleaned)) return "";
  return cleaned;
}

function getErrorMessage(error) {
  if (!error) return "";
  if (error.status === 400) return error.message || "Проверьте поля формы.";
  if (error.status === 401) return "Сессия истекла или нужен вход.";
  if (error.status === 503) return "Сервис рекомендаций пока недоступен.";
  if (error.status === 502) return "Погодный сервис временно не ответил.";
  return error.message || "Что-то пошло не так.";
}

function toTelegram2FAForm(settings = {}) {
  return {
    ...DEFAULT_TELEGRAM_2FA_FORM,
    telegram_username: settings.telegram_username || "",
    frequency: settings.frequency || "week",
    is_enabled: Boolean(settings.is_enabled),
    is_linked: Boolean(settings.is_linked),
    telegram_bot_url: settings.telegram_bot_url || DEFAULT_TELEGRAM_2FA_FORM.telegram_bot_url,
    telegram_bot_username: settings.telegram_bot_username || DEFAULT_TELEGRAM_2FA_FORM.telegram_bot_username,
    code: "",
  };
}

function toIotConfigForm(config = {}) {
  return {
    connection_mode: config.connection_mode || DEFAULT_IOT_CONFIG_FORM.connection_mode,
    serial_port: config.serial_port || config.serial?.port || DEFAULT_IOT_CONFIG_FORM.serial_port,
    baud_rate: Number(config.baud_rate || config.serial?.baud_rate || DEFAULT_IOT_CONFIG_FORM.baud_rate),
    linked_device_id: config.linked_device?.id ? String(config.linked_device.id) : "",
    enabled: Boolean(config.enabled ?? config.serial?.enabled),
    mqtt_enabled: Boolean(config.mqtt?.enabled),
    mqtt_host: config.mqtt?.host || DEFAULT_IOT_CONFIG_FORM.mqtt_host,
    mqtt_port: Number(config.mqtt?.port || DEFAULT_IOT_CONFIG_FORM.mqtt_port),
    mqtt_topic: config.mqtt?.topic || DEFAULT_IOT_CONFIG_FORM.mqtt_topic,
    mqtt_username: config.mqtt?.username || "",
    mqtt_password: "",
  };
}

function validateAuthForm(mode, form) {
  const username = form.username.trim();
  const email = form.email.trim();
  const password = form.password;

  if (!username) {
    throw new Error(mode === "register" ? "Введите никнейм." : "Введите никнейм или email.");
  }

  if (mode === "register") {
    if (!email) throw new Error("Введите email.");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new Error("Введите корректный email.");
  }

  if (!password) throw new Error("Введите пароль.");
  if (mode === "register" && password.length < 8) {
    throw new Error("Пароль должен быть не короче 8 символов.");
  }

  return { username, email, password };
}

function App() {
  const [tokens, setTokens] = useState(() => readTokens());
  const [theme, setTheme] = useState(getInitialTheme);
  const [pathname, setPathname] = useState(window.location.pathname);
  const [authMode, setAuthMode] = useState(() => (window.location.pathname.includes("register") ? "register" : "login"));
  const [authForm, setAuthForm] = useState({ username: "", email: "", password: "" });
  const [authStatus, setAuthStatus] = useState("");
  const [searchMode, setSearchMode] = useState("city");
  const [themeBurst, setThemeBurst] = useState(false);
  const [sectionPulse, setSectionPulse] = useState("");
  const [coords, setCoords] = useState(DEFAULT_COORDS);
  const [weather, setWeather] = useState(null);
  const [extendedOpen, setExtendedOpen] = useState(false);
  const [extendedWeather, setExtendedWeather] = useState(null);
  const [extendedLoadedKey, setExtendedLoadedKey] = useState("");
  const [weatherHistory, setWeatherHistory] = useState([]);
  const [outfit, setOutfit] = useState(null);
  const [stationId, setStationId] = useState("arduino-1");
  const [stationLatest, setStationLatest] = useState(null);
  const [stationHistory, setStationHistory] = useState([]);
  const [dwdForm, setDwdForm] = useState(DEFAULT_DWD_FORM);
  const [dwdApplications, setDwdApplications] = useState([]);
  const [providerDashboard, setProviderDashboard] = useState(null);
  const [dwdNotifications, setDwdNotifications] = useState([]);
  const [dwdMessages, setDwdMessages] = useState({});
  const [chatDrafts, setChatDrafts] = useState({});
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [supportWidgetOpen, setSupportWidgetOpen] = useState(false);
  const [supportTickets, setSupportTickets] = useState([]);
  const [supportMessages, setSupportMessages] = useState({});
  const [supportDrafts, setSupportDrafts] = useState({});
  const [supportForm, setSupportForm] = useState(DEFAULT_SUPPORT_FORM);
  const [selectedSupportTicketId, setSelectedSupportTicketId] = useState("");
  const [adminDwdUsers, setAdminDwdUsers] = useState([]);
  const [adminDwdApplications, setAdminDwdApplications] = useState([]);
  const [adminDwdDevices, setAdminDwdDevices] = useState([]);
  const [adminDwdProvisioning, setAdminDwdProvisioning] = useState([]);
  const [adminDwdEvents, setAdminDwdEvents] = useState([]);
  const [adminStationRequests, setAdminStationRequests] = useState([]);
  const [adminAiOutfits, setAdminAiOutfits] = useState([]);
  const [adminIotConfig, setAdminIotConfig] = useState(null);
  const [adminIotStatus, setAdminIotStatus] = useState(null);
  const [iotConfigForm, setIotConfigForm] = useState(DEFAULT_IOT_CONFIG_FORM);
  const [provisioningForm, setProvisioningForm] = useState(DEFAULT_PROVISIONING_FORM);
  const [providerFirmwareForm, setProviderFirmwareForm] = useState(DEFAULT_PROVIDER_FIRMWARE_FORM);
  const [profile, setProfile] = useState(null);
  const [profileForm, setProfileForm] = useState(DEFAULT_PROFILE_FORM);
  const [passwordForm, setPasswordForm] = useState(DEFAULT_PASSWORD_FORM);
  const [telegram2FAForm, setTelegram2FAForm] = useState(DEFAULT_TELEGRAM_2FA_FORM);
  const [login2FAChallenge, setLogin2FAChallenge] = useState(null);
  const [login2FAForm, setLogin2FAForm] = useState(DEFAULT_LOGIN_2FA_FORM);
  const [isDwdAdmin, setIsDwdAdmin] = useState(false);
  const [loading, setLoading] = useState({ weather: false, extended: false, station: false, auth: false, dwd: false, profile: false });
  const [notice, setNotice] = useState("");

  const isAuthenticated = Boolean(tokens?.access);

  useEffect(() => {
    loadWeather();
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      loadProfile(tokens);
      loadStation(tokens);
      loadDwd(tokens);
    } else {
      setStationLatest(null);
      setStationHistory([]);
      setExtendedOpen(false);
      setExtendedWeather(null);
      setExtendedLoadedKey("");
      setDwdApplications([]);
      setProviderDashboard(null);
      setDwdNotifications([]);
      setDwdMessages({});
      setChatDrafts({});
      setSupportTickets([]);
      setSupportMessages({});
      setSupportDrafts({});
      setSupportForm(DEFAULT_SUPPORT_FORM);
      setSelectedSupportTicketId("");
      setNotificationsOpen(false);
      setSupportWidgetOpen(false);
      setAdminDwdUsers([]);
      setAdminDwdApplications([]);
      setAdminDwdDevices([]);
      setAdminDwdProvisioning([]);
      setAdminDwdEvents([]);
      setAdminStationRequests([]);
      setAdminAiOutfits([]);
      setAdminIotConfig(null);
      setAdminIotStatus(null);
      setIotConfigForm(DEFAULT_IOT_CONFIG_FORM);
      setProviderFirmwareForm(DEFAULT_PROVIDER_FIRMWARE_FORM);
      setProfile(null);
      setProfileForm(DEFAULT_PROFILE_FORM);
      setPasswordForm(DEFAULT_PASSWORD_FORM);
      setIsDwdAdmin(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    const devices = providerDashboard?.devices || [];
    if (!devices.length) return;
    setProviderFirmwareForm((current) => {
      if (current.device_id) return current;
      return { ...current, device_id: String(devices[0].id) };
    });
  }, [providerDashboard]);

  useEffect(() => {
    const handlePopState = () => {
      setPathname(window.location.pathname);
      setAuthMode(window.location.pathname.includes("register") ? "register" : "login");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [isAuthenticated, pathname]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    const revealItems = document.querySelectorAll(".reveal");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.18, rootMargin: "0px 0px -8% 0px" },
    );

    revealItems.forEach((item) => {
      const rect = item.getBoundingClientRect();
      const isInViewport = rect.top < window.innerHeight && rect.bottom > 0;

      if (isInViewport) {
        item.classList.add("is-visible");
      } else {
        observer.observe(item);
      }
    });
    return () => observer.disconnect();
  }, [
    pathname,
    isAuthenticated,
    weather,
    extendedOpen,
    extendedWeather,
    outfit,
    notice,
    weatherHistory.length,
    stationHistory.length,
    stationLatest,
    dwdApplications.length,
    providerDashboard,
    dwdNotifications.length,
    supportTickets.length,
    adminDwdUsers.length,
    adminDwdApplications.length,
    adminDwdDevices.length,
    adminDwdProvisioning.length,
    adminDwdEvents.length,
    profile,
  ]);

  async function runTask(key, task) {
    setLoading((current) => ({ ...current, [key]: true }));
    setNotice("");
    logUi("task_started", { key });
    try {
      await task();
    } catch (error) {
      console.error(`[dwv2:ui] task_failed:${key}`, error);
      setNotice(getErrorMessage(error));
    } finally {
      logUi("task_finished", { key });
      setLoading((current) => ({ ...current, [key]: false }));
    }
  }

  async function loadProfile(nextTokens = tokens) {
    if (!nextTokens?.access) return;
    await runTask("profile", async () => {
      const nextProfile = await getProfile(nextTokens);
      setProfile(nextProfile);
      setProfileForm({
        username: nextProfile.username || "",
        email: nextProfile.email || "",
      });
      setTelegram2FAForm(toTelegram2FAForm(nextProfile.telegram_2fa));
    });
  }

  async function handleProfileSubmit(event) {
    event.preventDefault();
    if (!tokens?.access) {
      navigate("/login");
      return;
    }

    await runTask("profile", async () => {
      const nextProfile = await updateProfile(
        {
          username: profileForm.username.trim(),
          email: profileForm.email.trim(),
        },
        tokens,
      );
      setProfile(nextProfile);
      setProfileForm({ username: nextProfile.username || "", email: nextProfile.email || "" });
      setNotice("Профиль обновлён.");
    });
  }

  async function handlePasswordSubmit(event) {
    event.preventDefault();
    if (!tokens?.access) {
      navigate("/login");
      return;
    }

    await runTask("profile", async () => {
      await changePassword(passwordForm, tokens);
      setPasswordForm(DEFAULT_PASSWORD_FORM);
      setNotice("Пароль изменён. В следующий раз используйте новый пароль.");
    });
  }

  async function handleTelegram2FAStart(event) {
    event.preventDefault();
    if (!tokens?.access) return navigate("/login");

    await runTask("profile", async () => {
      const response = await startTelegram2FASetup(telegram2FAForm.telegram_username, tokens);
      setTelegram2FAForm(toTelegram2FAForm(response.telegram_2fa));
      setProfile((current) => current ? { ...current, telegram_2fa: response.telegram_2fa } : current);
      setNotice(`Откройте ${response.telegram_bot_username} и напишите боту любое сообщение. Он пришлёт код привязки.`);
    });
  }

  async function handleTelegram2FAVerify(event) {
    event.preventDefault();
    if (!tokens?.access) return navigate("/login");

    await runTask("profile", async () => {
      const settings = await verifyTelegram2FASetup(telegram2FAForm.code, tokens);
      setTelegram2FAForm(toTelegram2FAForm(settings));
      setProfile((current) => current ? { ...current, telegram_2fa: settings } : current);
      setNotice("Telegram привязан, 2FA включена.");
    });
  }

  async function handleTelegram2FASettingsSubmit(event) {
    event.preventDefault();
    if (!tokens?.access) return navigate("/login");

    await runTask("profile", async () => {
      const settings = await updateTelegram2FASettings(
        {
          is_enabled: telegram2FAForm.is_enabled,
          frequency: telegram2FAForm.frequency,
        },
        tokens,
      );
      setTelegram2FAForm(toTelegram2FAForm(settings));
      setProfile((current) => current ? { ...current, telegram_2fa: settings } : current);
      setNotice(settings.is_enabled ? "Настройки Telegram 2FA сохранены." : "Telegram 2FA отключена.");
    });
  }

  async function handleDeleteAccount() {
    if (!tokens?.access) return;
    const confirmed = window.confirm("Удалить аккаунт? Это действие нельзя отменить.");
    if (!confirmed) return;

    await runTask("profile", async () => {
      await deleteProfile(tokens);
      clearTokens();
      setTokens(null);
      setProfile(null);
      setTelegram2FAForm(DEFAULT_TELEGRAM_2FA_FORM);
      setNotice("Аккаунт удалён.");
      navigate("/login");
    });
  }

  async function handleLogin2FASubmit(event) {
    event.preventDefault();
    if (!login2FAChallenge?.challenge_id) return;

    await runTask("auth", async () => {
      const nextTokens = await verifyTelegramLogin(login2FAChallenge.challenge_id, login2FAForm.code);
      saveTokens(nextTokens);
      setTokens(nextTokens);
      setLogin2FAChallenge(null);
      setLogin2FAForm(DEFAULT_LOGIN_2FA_FORM);
      setAuthStatus("Вход подтверждён через Telegram.");
      await loadProfile(nextTokens);
      await loadWeather(nextTokens);
      await loadStation(nextTokens);
      await loadDwd(nextTokens);
      navigate("/weather");
    });
  }

  async function handleAuth(event) {
    event.preventDefault();
    setAuthStatus("");

    await runTask("auth", async () => {
      const cleanedForm = validateAuthForm(authMode, authForm);

      if (authMode === "register") {
        await signup(cleanedForm.username, cleanedForm.email, cleanedForm.password);
        setAuthMode("login");
        setAuthStatus("Аккаунт создан. Теперь можно войти.");
        navigate("/login");
        return;
      }

      const nextTokens = await login(cleanedForm.username, cleanedForm.password);
      if (nextTokens?.two_factor_required) {
        setLogin2FAChallenge(nextTokens);
        setLogin2FAForm(DEFAULT_LOGIN_2FA_FORM);
        setAuthStatus(`Код отправлен в Telegram. Бот: ${nextTokens.telegram_bot_username}.`);
        return;
      }
      setLogin2FAChallenge(null);
      setLogin2FAForm(DEFAULT_LOGIN_2FA_FORM);
      saveTokens(nextTokens);
      setTokens(nextTokens);
      setAuthStatus("Вход выполнен.");
      await loadProfile(nextTokens);
      await loadWeather(nextTokens);
      await loadStation(nextTokens);
      await loadDwd(nextTokens);
      navigate("/weather");
    });
  }

  function handleLogout() {
    clearTokens();
    setTokens(null);
    setWeatherHistory([]);
    setExtendedOpen(false);
    setExtendedWeather(null);
    setExtendedLoadedKey("");
    setStationLatest(null);
    setStationHistory([]);
    setDwdApplications([]);
    setProviderDashboard(null);
    setAdminDwdUsers([]);
    setAdminDwdApplications([]);
    setAdminDwdDevices([]);
    setAdminDwdProvisioning([]);
    setAdminDwdEvents([]);
    setProfile(null);
    setProfileForm(DEFAULT_PROFILE_FORM);
    setPasswordForm(DEFAULT_PASSWORD_FORM);
    setTelegram2FAForm(DEFAULT_TELEGRAM_2FA_FORM);
    setLogin2FAChallenge(null);
    setLogin2FAForm(DEFAULT_LOGIN_2FA_FORM);
    setIsDwdAdmin(false);
    setAuthStatus("Вы вышли из аккаунта.");
  }

  function navigate(path) {
    window.history.pushState({}, "", path);
    setPathname(path);
    setAuthMode(path.includes("register") ? "register" : "login");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function toggleTheme() {
    setThemeBurst(false);
    requestAnimationFrame(() => {
      setThemeBurst(true);
      setTheme((current) => (current === "dark" ? "light" : "dark"));
      window.setTimeout(() => setThemeBurst(false), 760);
    });
  }

  function focusSection(sectionId) {
    if (sectionId === "weather") {
      navigate("/weather");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      const section = document.getElementById(sectionId);
      section?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    setSectionPulse("");
    window.setTimeout(() => setSectionPulse(sectionId), 20);
    window.setTimeout(() => setSectionPulse(""), 1050);
  }

  async function resolveCity() {
    if (!coords.city.trim()) return coords;
    logUi("geocode_started", { city: coords.city.trim() });
    const place = await geocodeCity(coords.city.trim());
    const nextCoords = {
      city: place.city,
      lat: String(place.latitude),
      lon: String(place.longitude),
    };
    setCoords(nextCoords);
    logUi("geocode_finished", nextCoords);
    return nextCoords;
  }

  async function loadWeather(nextTokens = tokens, nextCoords = coords) {
    await runTask("weather", async () => {
      const target = searchMode === "city" ? await resolveCity() : nextCoords;
      const params = new URLSearchParams({ lat: target.lat, lon: target.lon });
      setExtendedOpen(false);
      setExtendedWeather(null);
      setExtendedLoadedKey("");
      logUi("weather_load_started", { target, authenticated: Boolean(nextTokens?.access) });
      const current = await apiRequest(`/weather?${params}`);
      setWeather(current);
      logUi("weather_current_loaded", {
        source: current.source,
        cache_status: current.cache_status,
        observed_at: current.observed_at,
        temperature_c: current.temperature_c,
      });

      const condition = current.precipitation_mm > 0 ? "rain" : "cloudy";
      apiRequest("/ai/outfit-recommendation", {
        method: "POST",
        body: JSON.stringify({
          city: target.city || "Выбранная локация",
          temperature_c: current.temperature_c,
          humidity: stationLatest?.reading?.humidity ?? stationLatest?.humidity ?? 70,
          wind_speed_ms: current.wind_speed_ms,
          precipitation_mm: current.precipitation_mm,
          condition,
        }),
      })
        .then(setOutfit)
        .catch((error) => {
          console.error("[dwv2:ui] outfit_failed", error);
          setOutfit({ recommendation: getErrorMessage(error), source: "unavailable" });
        });

      await loadWeatherHistory(params, nextTokens);
      await loadStation(nextTokens, target);
    });
  }

  function getExtendedKey(target = coords) {
    return `${target.city || ""}:${target.lat}:${target.lon}:7`;
  }

  async function loadExtendedWeather(nextTokens = tokens, target = coords) {
    if (!nextTokens?.access) return;

    const key = getExtendedKey(target);
    if (extendedWeather && extendedLoadedKey === key) return;

    await runTask("extended", async () => {
      const payload = await getExtendedWeather(
        {
          city: target.city || "",
          lat: target.lat,
          lon: target.lon,
          days: 7,
        },
        nextTokens,
      );
      setExtendedWeather(payload);
      setExtendedLoadedKey(key);
    });
  }

  async function handleExtendedToggle() {
    const nextOpen = !extendedOpen;
    setExtendedOpen(nextOpen);
    if (nextOpen && isAuthenticated) {
      await loadExtendedWeather(tokens, coords);
    }
  }

  async function loadWeatherHistory(params, nextTokens = tokens) {
    if (!nextTokens?.access) {
      setWeatherHistory([]);
      return;
    }

    try {
      const history = await apiRequest(`/weather/history?${params}&limit=24`, {}, nextTokens);
      setWeatherHistory(history.results || []);
      logUi("weather_history_loaded", { results: history.results?.length || 0 });
    } catch (error) {
      setWeatherHistory([]);
      console.error("[dwv2:ui] weather_history_failed", error);
      if (error.status === 401) {
        clearTokens();
        setTokens(null);
      }
      setNotice(`Погода обновлена, но история недоступна: ${getErrorMessage(error)}`);
    }
  }

  async function loadStation(nextTokens = tokens, target = coords) {
    if (!nextTokens?.access) return;
    await runTask("station", async () => {
      const city = target.city || coords.city;
      const params = city ? new URLSearchParams({ city }) : new URLSearchParams({ station_id: stationId });
      const history = await apiRequest(`/station/history?${params}&limit=100`);
      setStationHistory(history.results || []);
      logUi("station_history_loaded", { city, stationId, results: history.results?.length || 0 });

      try {
        const latest = await apiRequest(`/station/latest?${params}`);
        setStationLatest(latest);
        logUi("station_latest_loaded", { city, stationId, available: latest.available, readingId: latest.reading?.id || latest.id });
      } catch (error) {
        if (error.status === 404) {
          setStationLatest(null);
          logUi("station_latest_empty", { stationId });
          return;
        }
        throw error;
      }
    });
  }

  async function refreshDwdData(nextTokens = tokens) {
    if (!nextTokens?.access) return;

    const ownApplications = await listProviderApplications(nextTokens);
    setDwdApplications(Array.isArray(ownApplications) ? ownApplications : []);
    const messageApplications = Array.isArray(ownApplications) ? [...ownApplications] : [];
    const notifications = await listDwdNotifications(nextTokens, { limit: 50 });
    setDwdNotifications(Array.isArray(notifications) ? notifications : []);
    const tickets = await listSupportTickets(nextTokens, { limit: 50 });
    const ticketList = Array.isArray(tickets) ? tickets : [];
    setSupportTickets(ticketList);
    if (!selectedSupportTicketId && ticketList[0]?.id) {
      setSelectedSupportTicketId(String(ticketList[0].id));
    }
    try {
      setProviderDashboard(await getProviderDashboard(nextTokens));
    } catch (error) {
      if (error.status !== 403) throw error;
      setProviderDashboard(null);
    }

    try {
      const [users, applications, devices, provisioning, events, stationRequests, aiOutfits, iotConfig, iotStatus] = await Promise.all([
        listAdminDwdUsers(nextTokens),
        listAdminDwdApplications(nextTokens),
        listAdminDwdDevices(nextTokens),
        listAdminDwdProvisioning(nextTokens),
        listAdminDwdDeviceEvents(nextTokens, { limit: 200 }),
        listStationRequests(nextTokens, { limit: 100 }),
        listAdminAiOutfitRecommendations(nextTokens, { limit: 100 }),
        getAdminIotConfig(nextTokens),
        getAdminIotStatus(nextTokens),
      ]);
      setAdminDwdUsers(Array.isArray(users) ? users : []);
      setAdminDwdApplications(Array.isArray(applications) ? applications : []);
      if (Array.isArray(applications)) messageApplications.push(...applications);
      setAdminDwdDevices(Array.isArray(devices) ? devices : []);
      setAdminDwdProvisioning(Array.isArray(provisioning) ? provisioning : []);
      setAdminDwdEvents(Array.isArray(events) ? events : []);
      setAdminStationRequests(Array.isArray(stationRequests?.results) ? stationRequests.results : []);
      setAdminAiOutfits(Array.isArray(aiOutfits) ? aiOutfits : []);
      setAdminIotConfig(iotConfig || null);
      setAdminIotStatus(iotStatus || null);
      setIotConfigForm(toIotConfigForm(iotConfig));
      setIsDwdAdmin(true);
    } catch (error) {
      if (error.status === 403) {
        setAdminDwdUsers([]);
        setAdminDwdApplications([]);
        setAdminDwdDevices([]);
        setAdminDwdProvisioning([]);
        setAdminDwdEvents([]);
        setAdminStationRequests([]);
        setAdminAiOutfits([]);
        setAdminIotConfig(null);
        setAdminIotStatus(null);
        setIotConfigForm(DEFAULT_IOT_CONFIG_FORM);
        setIsDwdAdmin(false);
        await refreshDwdMessages(messageApplications, nextTokens);
        await refreshSupportMessages(ticketList, nextTokens);
        return;
      }
      if (error.status === 401) {
        clearTokens();
        setTokens(null);
      }
      throw error;
    }
    await refreshDwdMessages(messageApplications, nextTokens);
    await refreshSupportMessages(ticketList, nextTokens);
  }

  async function refreshDwdMessages(applications, nextTokens = tokens) {
    const ids = [...new Set((applications || []).map((item) => item?.id).filter(Boolean))];
    if (!ids.length || !nextTokens?.access) return;
    const entries = await Promise.all(ids.map(async (id) => {
      try {
        const messages = await listDwdApplicationMessages(id, nextTokens);
        return [id, Array.isArray(messages) ? messages : []];
      } catch (error) {
        if (error.status === 403 || error.status === 404) return [id, []];
        throw error;
      }
    }));
    setDwdMessages((current) => ({ ...current, ...Object.fromEntries(entries) }));
  }

  async function refreshSupportMessages(tickets, nextTokens = tokens) {
    const ids = [...new Set((tickets || []).map((item) => item?.id).filter(Boolean))];
    if (!ids.length || !nextTokens?.access) return;
    const entries = await Promise.all(ids.map(async (id) => {
      try {
        const messages = await listSupportTicketMessages(id, nextTokens);
        return [id, Array.isArray(messages) ? messages : []];
      } catch (error) {
        if (error.status === 403 || error.status === 404) return [id, []];
        throw error;
      }
    }));
    setSupportMessages((current) => ({ ...current, ...Object.fromEntries(entries) }));
  }

  async function loadDwd(nextTokens = tokens) {
    if (!nextTokens?.access) return;
    await runTask("dwd", async () => {
      await refreshDwdData(nextTokens);
    });
  }

  async function handleDwdApplicationSubmit(event) {
    event.preventDefault();
    if (!tokens?.access) {
      navigate("/login");
      return;
    }

    const city = dwdForm.city.trim();
    const email = dwdForm.email.trim();
    const comment = dwdForm.comment.trim();
    if (!city || !email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !comment) {
      setNotice("Укажите город, корректный email и комментарий к заявке.");
      return;
    }

    await runTask("dwd", async () => {
      await createProviderApplication({ city, email, comment }, tokens);
      setDwdForm(DEFAULT_DWD_FORM);
      await refreshDwdData(tokens);
      setNotice("DWD provider application submitted.");
    });
  }

  async function handleDwdApprove(applicationId) {
    await runTask("dwd", async () => {
      await approveDwdApplication(applicationId, tokens);
      await refreshDwdData(tokens);
      setNotice("Заявка DWD одобрена. Провайдер теперь может сам сгенерировать код прошивки в личном кабинете.");
    });
  }

  async function handleDwdReject(applicationId) {
    await runTask("dwd", async () => {
      await rejectDwdApplication(applicationId, tokens);
      await refreshDwdData(tokens);
      setNotice("Заявка DWD отклонена.");
    });
  }

  async function handleDwdRoleChange(userId, role) {
    await runTask("dwd", async () => {
      await updateAdminDwdUserRole(userId, role, tokens);
      await refreshDwdData(tokens);
      setNotice("Роль пользователя обновлена.");
    });
  }

  async function handleDwdUserDelete(userId) {
    const confirmed = window.confirm("Удалить аккаунт пользователя? Это действие нельзя отменить.");
    if (!confirmed) return;

    await runTask("dwd", async () => {
      await deleteAdminDwdUser(userId, tokens);
      await refreshDwdData(tokens);
      setNotice("Пользователь удалён.");
    });
  }

  async function handleApplicationNote(applicationId, adminNote) {
    await runTask("dwd", async () => {
      await updateAdminDwdApplication(applicationId, { admin_note: adminNote }, tokens);
      await refreshDwdData(tokens);
      setNotice("Заметка к заявке сохранена.");
    });
  }

  async function handleNotificationRead(notificationId) {
    await runTask("dwd", async () => {
      await markDwdNotificationRead(notificationId, tokens);
      const notifications = await listDwdNotifications(tokens, { limit: 50 });
      setDwdNotifications(Array.isArray(notifications) ? notifications : []);
    });
  }

  async function handleSupportMessageSubmit(applicationId) {
    const draft = (chatDrafts[applicationId] || "").trim();
    if (!draft) return;
    await runTask("dwd", async () => {
      await sendDwdApplicationMessage(applicationId, draft, tokens);
      setChatDrafts((current) => ({ ...current, [applicationId]: "" }));
      const messages = await listDwdApplicationMessages(applicationId, tokens);
      setDwdMessages((current) => ({ ...current, [applicationId]: Array.isArray(messages) ? messages : [] }));
      const notifications = await listDwdNotifications(tokens, { limit: 50 });
      setDwdNotifications(Array.isArray(notifications) ? notifications : []);
    });
  }

  async function handleSupportTicketCreate(event) {
    event.preventDefault();
    const subject = supportForm.subject.trim();
    const message = supportForm.message.trim();
    if (!subject || !message) {
      setNotice("Укажите тему и описание обращения.");
      return;
    }
    await runTask("dwd", async () => {
      const ticket = await createSupportTicket({
        subject,
        message,
        category: supportForm.category || "service",
      }, tokens);
      setSupportForm(DEFAULT_SUPPORT_FORM);
      setSelectedSupportTicketId(String(ticket.id));
      await refreshDwdData(tokens);
      setNotice("Обращение в техподдержку создано.");
    });
  }

  async function handleSupportTicketMessageSubmit(ticketId) {
    const draft = (supportDrafts[ticketId] || "").trim();
    if (!draft) return;
    await runTask("dwd", async () => {
      await sendSupportTicketMessage(ticketId, draft, tokens);
      setSupportDrafts((current) => ({ ...current, [ticketId]: "" }));
      const messages = await listSupportTicketMessages(ticketId, tokens);
      setSupportMessages((current) => ({ ...current, [ticketId]: Array.isArray(messages) ? messages : [] }));
      const tickets = await listSupportTickets(tokens, { limit: 50 });
      setSupportTickets(Array.isArray(tickets) ? tickets : []);
      const notifications = await listDwdNotifications(tokens, { limit: 50 });
      setDwdNotifications(Array.isArray(notifications) ? notifications : []);
    });
  }

  async function handleSupportTicketStatus(ticketId, status) {
    await runTask("dwd", async () => {
      await updateSupportTicket(ticketId, { status }, tokens);
      await refreshDwdData(tokens);
      setNotice("Статус тикета обновлён.");
    });
  }

  async function handleAiOutfitRegenerate(recommendationId) {
    await runTask("dwd", async () => {
      await regenerateAdminAiOutfitRecommendation(recommendationId, tokens);
      const aiOutfits = await listAdminAiOutfitRecommendations(tokens, { limit: 100 });
      setAdminAiOutfits(Array.isArray(aiOutfits) ? aiOutfits : []);
      setNotice("AI-совет перегенерирован.");
    });
  }

  async function handleDevicePatch(deviceId, payload) {
    await runTask("dwd", async () => {
      await updateAdminDwdDevice(deviceId, payload, tokens);
      await refreshDwdData(tokens);
      setNotice("Устройство обновлено.");
    });
  }

  async function handleDeviceAction(deviceId, action) {
    await runTask("dwd", async () => {
      await runAdminDwdDeviceAction(deviceId, action, tokens);
      await refreshDwdData(tokens);
      setNotice(`Действие с устройством выполнено: ${action}.`);
    });
  }

  function prepareProvisioning(application) {
    const device = application?.device;
    setProvisioningForm({
      ...DEFAULT_PROVISIONING_FORM,
      application_id: application?.id ? String(application.id) : "",
      user_id: application?.user?.id ? String(application.user.id) : "",
      device_id: device?.id ? String(device.id) : "",
    });
    navigate("/admin-panel/provisioning");
    window.setTimeout(() => document.getElementById("dwd-provisioning-form")?.scrollIntoView({ behavior: "smooth" }), 40);
  }

  function handleProvisioningField(field, value) {
    setProvisioningForm((current) => {
      if (field !== "firmware_type") return { ...current, [field]: value };
      return {
        ...current,
        firmware_type: value,
        instruction_text: current.instruction_text,
      };
    });
  }

  async function handleProvisioningSubmit(event) {
    event.preventDefault();
    if (!provisioningForm.application_id) {
      setNotice("Выберите одобренную DWD-заявку перед provisioning.");
      return;
    }

    const payload = {
      application_id: Number(provisioningForm.application_id),
      firmware_type: provisioningForm.firmware_type,
      firmware_version: provisioningForm.firmware_version,
      instruction_text: provisioningForm.instruction_text,
      wifi_ssid: provisioningForm.wifi_ssid,
      wifi_password: provisioningForm.wifi_password,
      delivery_channel: provisioningForm.delivery_channel,
      notes: provisioningForm.notes,
      internal_note: provisioningForm.notes,
    };
    if (provisioningForm.user_id) payload.user_id = Number(provisioningForm.user_id);
    if (provisioningForm.device_id) payload.device_id = Number(provisioningForm.device_id);

    await runTask("dwd", async () => {
      await createDwdProvisioning(payload, tokens);
      await refreshDwdData(tokens);
      setNotice("Код прошивки сгенерирован. Провайдер сможет скопировать его в личном кабинете.");
    });
  }

  async function handleProvisioningSent(provisioningId) {
    await runTask("dwd", async () => {
      await markDwdProvisioningSent(provisioningId, tokens);
      await refreshDwdData(tokens);
      setNotice("Инструкция отмечена как отправленная вручную.");
    });
  }

  function handleProviderFirmwareField(field, value) {
    setProviderFirmwareForm((current) => ({ ...current, [field]: value }));
  }

  async function handleProviderFirmwareSubmit(event) {
    event.preventDefault();
    const wifiSsid = providerFirmwareForm.wifi_ssid.trim();
    if (!wifiSsid) {
      setNotice("Укажите имя Wi-Fi сети для готовой прошивки.");
      return;
    }

    const payload = {
      device_id: providerFirmwareForm.device_id ? Number(providerFirmwareForm.device_id) : undefined,
      firmware_type: providerFirmwareForm.firmware_type,
      firmware_version: providerFirmwareForm.firmware_version,
      wifi_ssid: wifiSsid,
      wifi_password: providerFirmwareForm.wifi_password,
    };

    await runTask("dwd", async () => {
      const record = await generateProviderFirmware(payload, tokens);
      await refreshDwdData(tokens);
      setProviderFirmwareForm((current) => ({
        ...current,
        device_id: record.device?.id ? String(record.device.id) : current.device_id,
        firmware_type: record.firmware_type || current.firmware_type,
        firmware_version: record.firmware_version || current.firmware_version,
      }));
      setNotice("Код прошивки сгенерирован. Его можно скопировать из окна кода.");
    });
  }

  function handleIotConfigField(field, value) {
    setIotConfigForm((current) => ({ ...current, [field]: value }));
  }

  async function handleIotConfigSubmit(event) {
    event.preventDefault();
    const payload = {
      connection_mode: iotConfigForm.connection_mode,
      serial_port: iotConfigForm.serial_port.trim(),
      baud_rate: Number(iotConfigForm.baud_rate) || 9600,
      linked_device_id: iotConfigForm.linked_device_id ? Number(iotConfigForm.linked_device_id) : null,
      enabled: Boolean(iotConfigForm.enabled),
      mqtt_enabled: Boolean(iotConfigForm.mqtt_enabled),
      mqtt_host: iotConfigForm.mqtt_host.trim(),
      mqtt_port: Number(iotConfigForm.mqtt_port) || 1883,
      mqtt_topic: iotConfigForm.mqtt_topic.trim(),
      mqtt_username: iotConfigForm.mqtt_username.trim(),
    };
    if (iotConfigForm.mqtt_password) {
      payload.mqtt_password = iotConfigForm.mqtt_password;
    }

    await runTask("dwd", async () => {
      const updated = await updateAdminIotConfig(payload, tokens);
      const status = await getAdminIotStatus(tokens);
      setAdminIotConfig(updated);
      setAdminIotStatus(status);
      setIotConfigForm(toIotConfigForm(updated));
      setNotice("Настройки приёма станций сохранены.");
    });
  }

  const heroStyle = useMemo(() => {
    const temp = weather?.temperature_c ?? 12;
    const hue = temp < 0 ? 205 : temp > 25 ? 35 : 175;
    return { "--weather-hue": hue };
  }, [weather]);

  const isAuthPage = pathname.includes("login") || pathname.includes("register");
  const unreadDwdCount = dwdNotifications.filter((item) => !item.is_read).length;

  return (
    <div className={`app-shell ${themeBurst ? "theme-burst" : ""}`} style={heroStyle}>
      <div className="theme-wash" aria-hidden="true" />
      <div className="sky-orbit orbit-a" />
      <div className="sky-orbit orbit-b" />

      <header className="topbar glass-panel">
        <a className="brand" href="/weather" aria-label="Dark Weather" onClick={(event) => { event.preventDefault(); navigate("/weather"); }}>
          <span className="brand-mark"><CloudSun size={24} /></span>
          <span>Dark Weather</span>
        </a>
        <nav className="nav-links" aria-label="Навигация">
          <a href="/weather" onClick={(event) => { event.preventDefault(); navigate("/weather"); }}>Погода</a>
          <a href="/about" onClick={(event) => { event.preventDefault(); navigate("/about"); }}>О нас</a>
          <a href="/provider" onClick={(event) => { event.preventDefault(); navigate("/provider"); }}>Стать провайдером</a>
        </nav>
        <div className="auth-chip">
          <button
            className="icon-button theme-toggle"
            onClick={toggleTheme}
            title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
          >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          {isAuthenticated && (
            <>
              <div className="notification-menu">
              <button
                className="icon-button notification-button"
                onClick={() => setNotificationsOpen((value) => !value)}
                title="Уведомления"
                aria-label="Открыть уведомления"
                type="button"
              >
                <Bell size={18} />
                {unreadDwdCount > 0 && <span className="notification-dot">{unreadDwdCount}</span>}
              </button>
              {notificationsOpen && (
                <NotificationsDropdown
                  notifications={dwdNotifications}
                  onRead={handleNotificationRead}
                  navigate={navigate}
                  isAdmin={Boolean(profile?.is_staff || profile?.is_superuser || isDwdAdmin)}
                />
              )}
              </div>
              <button className="icon-button" onClick={() => navigate("/profile")} title="Профиль">
                <UserCircle size={18} />
              </button>
              {(profile?.is_staff || profile?.is_superuser || isDwdAdmin) && (
                <button className="icon-button" onClick={() => navigate("/admin-panel")} title="Админка">
                  <Settings size={18} />
                </button>
              )}
            </>
          )}
          {isAuthenticated ? (
            <button className="icon-button" onClick={handleLogout} title="Выйти">
              <LogOut size={18} />
            </button>
          ) : (
            <a className="small-link" href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }}>Войти</a>
          )}
        </div>
      </header>

      <SupportWidget
        isAuthenticated={isAuthenticated}
        isAdmin={Boolean(profile?.is_staff || profile?.is_superuser || isDwdAdmin)}
        open={supportWidgetOpen}
        setOpen={setSupportWidgetOpen}
        tickets={supportTickets}
        selectedTicketId={selectedSupportTicketId}
        setSelectedTicketId={setSelectedSupportTicketId}
        messagesByTicket={supportMessages}
        drafts={supportDrafts}
        form={supportForm}
        setForm={setSupportForm}
        loading={loading.dwd}
        onCreate={handleSupportTicketCreate}
        onDraftChange={(ticketId, value) => setSupportDrafts((current) => ({ ...current, [ticketId]: value }))}
        onSend={handleSupportTicketMessageSubmit}
        onStatusChange={handleSupportTicketStatus}
        navigate={navigate}
      />

      {isAuthPage ? (
        <main className="auth-page">
          <section className="auth-hero glass-panel reveal is-visible">
            <span className="eyebrow">Доступ к аккаунту</span>
            <h1>{authMode === "register" ? "Регистрация" : "Вход"}</h1>
            <p>После авторизации откроются приватные погодные графики и телеметрия Arduino станции.</p>
          </section>
          <AuthPanel
            authMode={authMode}
            authForm={authForm}
            authStatus={authStatus}
            login2FAChallenge={login2FAChallenge}
            login2FAForm={login2FAForm}
            loading={loading.auth}
            setAuthForm={setAuthForm}
            setAuthMode={setAuthMode}
            setLogin2FAChallenge={setLogin2FAChallenge}
            setLogin2FAForm={setLogin2FAForm}
            handleAuth={handleAuth}
            handleLogin2FASubmit={handleLogin2FASubmit}
            navigate={navigate}
          />
        </main>
      ) : pathname.includes("about") ? (
        <AboutPage />
      ) : pathname.includes("provider") ? (
        <ProviderPage
          isAuthenticated={isAuthenticated}
          dwdForm={dwdForm}
          setDwdForm={setDwdForm}
          dwdApplications={dwdApplications}
          providerDashboard={providerDashboard}
          providerFirmwareForm={providerFirmwareForm}
          notifications={dwdNotifications}
          messagesByApplication={dwdMessages}
          chatDrafts={chatDrafts}
          supportTickets={supportTickets}
          supportMessages={supportMessages}
          supportDrafts={supportDrafts}
          loading={loading.dwd}
          handleDwdApplicationSubmit={handleDwdApplicationSubmit}
          onProviderFirmwareFieldChange={handleProviderFirmwareField}
          onProviderFirmwareSubmit={handleProviderFirmwareSubmit}
          onNotificationRead={handleNotificationRead}
          onChatDraftChange={(applicationId, value) => setChatDrafts((current) => ({ ...current, [applicationId]: value }))}
          onSupportMessageSubmit={handleSupportMessageSubmit}
          onSupportDraftChange={(ticketId, value) => setSupportDrafts((current) => ({ ...current, [ticketId]: value }))}
          onSupportTicketMessageSubmit={handleSupportTicketMessageSubmit}
          onSupportTicketStatus={handleSupportTicketStatus}
          navigate={navigate}
        />
      ) : pathname.includes("profile") ? (
        <ProfilePage
          isAuthenticated={isAuthenticated}
          profile={profile}
          profileForm={profileForm}
          passwordForm={passwordForm}
          telegram2FAForm={telegram2FAForm}
          loading={loading.profile}
          setProfileForm={setProfileForm}
          setPasswordForm={setPasswordForm}
          setTelegram2FAForm={setTelegram2FAForm}
          handleProfileSubmit={handleProfileSubmit}
          handlePasswordSubmit={handlePasswordSubmit}
          handleTelegram2FAStart={handleTelegram2FAStart}
          handleTelegram2FAVerify={handleTelegram2FAVerify}
          handleTelegram2FASettingsSubmit={handleTelegram2FASettingsSubmit}
          handleDeleteAccount={handleDeleteAccount}
          navigate={navigate}
        />
      ) : pathname.includes("admin-panel") ? (
        <AdminPanelPage
          isAuthenticated={isAuthenticated}
          isDwdAdmin={Boolean(profile?.is_staff || profile?.is_superuser || isDwdAdmin)}
          pathname={pathname}
          users={adminDwdUsers}
          applications={adminDwdApplications}
          devices={adminDwdDevices}
          provisioningRecords={adminDwdProvisioning}
          events={adminDwdEvents}
          stationRequests={adminStationRequests}
          aiOutfits={adminAiOutfits}
          iotConfig={adminIotConfig}
          iotStatus={adminIotStatus}
          iotConfigForm={iotConfigForm}
          provisioningForm={provisioningForm}
          notifications={dwdNotifications}
          messagesByApplication={dwdMessages}
          chatDrafts={chatDrafts}
          supportTickets={supportTickets}
          supportMessages={supportMessages}
          supportDrafts={supportDrafts}
          loading={loading.dwd}
          loadDwd={loadDwd}
          onRoleChange={handleDwdRoleChange}
          onUserDelete={handleDwdUserDelete}
          onApprove={handleDwdApprove}
          onReject={handleDwdReject}
          onApplicationNote={handleApplicationNote}
          onDevicePatch={handleDevicePatch}
          onDeviceAction={handleDeviceAction}
          onPrepareProvisioning={prepareProvisioning}
          onProvisioningFieldChange={handleProvisioningField}
          onProvisioningSubmit={handleProvisioningSubmit}
          onProvisioningSent={handleProvisioningSent}
          onIotConfigFieldChange={handleIotConfigField}
          onIotConfigSubmit={handleIotConfigSubmit}
          onNotificationRead={handleNotificationRead}
          onChatDraftChange={(applicationId, value) => setChatDrafts((current) => ({ ...current, [applicationId]: value }))}
          onSupportMessageSubmit={handleSupportMessageSubmit}
          onSupportDraftChange={(ticketId, value) => setSupportDrafts((current) => ({ ...current, [ticketId]: value }))}
          onSupportTicketMessageSubmit={handleSupportTicketMessageSubmit}
          onSupportTicketStatus={handleSupportTicketStatus}
          onAiOutfitRegenerate={handleAiOutfitRegenerate}
          navigate={navigate}
        />
      ) : (
      <main className="main-grid">
        <section className={`hero-panel glass-panel reveal is-visible ${sectionPulse === "weather" ? "section-pulse" : ""}`}>
          <div className="hero-copy">
            <span className="eyebrow">Dark Weather</span>
            <h1>{coords.city || "Выбранная локация"}</h1>
            <p>Погода сейчас, совет по одежде, прогноз на несколько дней и данные ближайшей локальной станции.</p>
          </div>

          <form className="search-console" onSubmit={(event) => { event.preventDefault(); loadWeather(); }}>
            <div className="mode-switch" role="tablist" aria-label="Режим поиска погоды">
              <button
                className={searchMode === "city" ? "active" : ""}
                type="button"
                role="tab"
                aria-selected={searchMode === "city"}
                onClick={() => setSearchMode("city")}
              >
                Город
              </button>
              <button
                className={searchMode === "coords" ? "active" : ""}
                type="button"
                role="tab"
                aria-selected={searchMode === "coords"}
                onClick={() => setSearchMode("coords")}
              >
                Координаты
              </button>
            </div>
            {searchMode === "city" ? (
              <label className="city-field">
                <span>Название города</span>
                <input value={coords.city} onChange={(event) => setCoords({ ...coords, city: event.target.value })} placeholder="Москва" />
              </label>
            ) : (
              <>
                <label>
                  <span>Широта</span>
                  <input value={coords.lat} onChange={(event) => setCoords({ ...coords, lat: event.target.value })} inputMode="decimal" />
                </label>
                <label>
                  <span>Долгота</span>
                  <input value={coords.lon} onChange={(event) => setCoords({ ...coords, lon: event.target.value })} inputMode="decimal" />
                </label>
              </>
            )}
            <button className="primary-button" type="submit" disabled={loading.weather}>
              {loading.weather ? <RefreshCw className="spin" size={18} /> : <Search size={18} />}
              Обновить
            </button>
          </form>
        </section>

        <aside className="access-panel glass-panel reveal is-visible">
          {isAuthenticated ? (
            <>
              <div className="panel-title">
                <Sparkles size={20} />
                <h2>Аккаунт подключён</h2>
              </div>
              <p className="empty-state">История погоды и локальная станция доступны ниже.</p>
            </>
          ) : (
            <>
              <div className="panel-title">
                <Lock size={20} />
                <h2>Нужен вход</h2>
              </div>
              <p className="empty-state">Войдите в аккаунт, чтобы увидеть историю погоды и данные локальной станции.</p>
              <div className="access-actions">
                <button className="primary-button" onClick={() => navigate("/login")}><LogIn size={18} />Войти</button>
                <button className="icon-text-button" onClick={() => navigate("/register")}><UserPlus size={18} />Регистрация</button>
              </div>
            </>
          )}
        </aside>

        {notice && <div className="notice glass-panel reveal is-visible">{notice}</div>}

        <section className="metric-board">
          <WeatherCard weather={weather} />
          <OutfitCard outfit={outfit} />
        </section>

        <ExtendedForecastSection
          isAuthenticated={isAuthenticated}
          open={extendedOpen}
          data={extendedWeather}
          loading={loading.extended}
          onToggle={handleExtendedToggle}
          navigate={navigate}
        />

        <section className={`charts-section glass-panel reveal ${sectionPulse === "charts" ? "section-pulse" : ""}`} id="charts">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Доступно после входа</span>
              <h2>История погоды</h2>
            </div>
            {!isAuthenticated && <span className="locked-pill">Нужен вход</span>}
          </div>
          {isAuthenticated ? (
            <div className="chart-grid">
              <LineChart title="Температура" unit="C" data={weatherHistory} dataKey="temperature_c" color="#18a0fb" />
              <LineChart title="Давление" unit="hPa" data={weatherHistory} dataKey="pressure_hpa" color="#7c67ff" />
              <LineChart title="Ветер" unit="m/s" data={weatherHistory} dataKey="wind_speed_ms" color="#00b894" />
            </div>
          ) : (
            <AccessGate navigate={navigate} text="Графики доступны только авторизованным пользователям." />
          )}
        </section>

        <section className={`station-section glass-panel reveal ${sectionPulse === "station" ? "section-pulse" : ""}`} id="station">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Локальная станция</span>
              <h2>Локальная погода</h2>
            </div>
            {isAuthenticated && (
              <div className="station-controls">
                <span className="city-chip">{coords.city || "выбранный город"}</span>
                <button className="icon-button" onClick={() => loadStation(tokens, coords)} title="Обновить локальную телеметрию">
                  {loading.station ? <RefreshCw className="spin" size={18} /> : <RefreshCw size={18} />}
                </button>
              </div>
            )}
          </div>
          {isAuthenticated ? (
            <>
              <StationLatest reading={stationLatest} />
              <div className="chart-grid station-charts">
                <LineChart title="Температура станции" unit="C" data={stationHistory} dataKey="temperature_c" color="#ff7a59" />
                <LineChart title="Влажность" unit="%" data={stationHistory} dataKey="humidity" color="#18c5c2" />
              </div>
            </>
          ) : (
            <AccessGate navigate={navigate} text="Последние данные локальной станции доступны только после входа." />
          )}
        </section>

      </main>
      )}
    </div>
  );
}

function AboutPage() {
  return (
    <main className="page-shell">
      <section className="info-page glass-panel reveal is-visible">
        <span className="eyebrow">О проекте Dark Weather</span>
        <h1>Погода, AI и локальные станции в одной системе</h1>
        <p>
          Dark Weather объединяет внешние погодные API, почасовое кеширование, AI-рекомендации по одежде
          и телеметрию Arduino. DWD-провайдеры подключают свои устройства вручную через заявку и прошивку.
        </p>
        <div className="info-grid">
          <article>
            <CloudSun size={22} />
            <strong>Погодные API</strong>
            <span>Race / First Complete выбирает первый успешный ответ провайдера.</span>
          </article>
          <article>
            <Sparkles size={22} />
            <strong>AI-рекомендации</strong>
            <span>Советы по одежде кешируются по городу и часу.</span>
          </article>
          <article>
            <Cpu size={22} />
            <strong>Готово к IoT</strong>
            <span>Arduino-данные принимаются через API, MQTT и Serial Bridge.</span>
          </article>
        </div>
      </section>
    </main>
  );
}

function ProviderPage({
  isAuthenticated,
  dwdForm,
  setDwdForm,
  dwdApplications,
  providerDashboard,
  providerFirmwareForm,
  notifications,
  messagesByApplication,
  chatDrafts,
  loading,
  handleDwdApplicationSubmit,
  onProviderFirmwareFieldChange,
  onProviderFirmwareSubmit,
  onNotificationRead,
  onChatDraftChange,
  onSupportMessageSubmit,
  navigate,
}) {
  const activeApplication = dwdApplications[0] || providerDashboard?.applications?.[0] || null;
  return (
    <main className="page-shell">
      <section className="provider-page glass-panel reveal is-visible">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Стать provider</span>
            <h1>Подключите свой город к DWD</h1>
          </div>
          <Radio size={28} />
        </div>
        <p className="empty-state">
          Укажите город, email для связи и комментарий. После одобрения вы сможете сами собрать готовый
          Arduino-код: сайт подставит station ID, MQTT topic и системные ключи автоматически.
        </p>
        {isAuthenticated ? (
          <>
            <DwdApplicationForm
              form={dwdForm}
              loading={loading}
              setForm={setDwdForm}
              onSubmit={handleDwdApplicationSubmit}
            />
            <DwdApplicationsList applications={dwdApplications} />
            <NotificationsPanel notifications={notifications} onRead={onNotificationRead} />
            <ProviderCabinet
              dashboard={providerDashboard}
              firmwareForm={providerFirmwareForm}
              loading={loading}
              onFirmwareFieldChange={onProviderFirmwareFieldChange}
              onFirmwareSubmit={onProviderFirmwareSubmit}
            />
            {activeApplication && (
              <SupportChat
                application={activeApplication}
                messages={messagesByApplication[activeApplication.id] || []}
                draft={chatDrafts[activeApplication.id] || ""}
                loading={loading}
                onDraftChange={onChatDraftChange}
                onSend={onSupportMessageSubmit}
                title="Чат с администратором"
              />
            )}
          </>
        ) : (
          <AccessGate navigate={navigate} text="Войдите, чтобы подать заявку DWD provider." />
        )}
      </section>
    </main>
  );
}

function ProfilePage({
  isAuthenticated,
  profile,
  profileForm,
  passwordForm,
  telegram2FAForm,
  loading,
  setProfileForm,
  setPasswordForm,
  setTelegram2FAForm,
  handleProfileSubmit,
  handlePasswordSubmit,
  handleTelegram2FAStart,
  handleTelegram2FAVerify,
  handleTelegram2FASettingsSubmit,
  handleDeleteAccount,
  navigate,
}) {
  if (!isAuthenticated) {
    return (
      <main className="page-shell">
        <section className="profile-page glass-panel reveal is-visible">
          <AccessGate navigate={navigate} text="Войдите, чтобы открыть профиль." />
        </section>
      </main>
    );
  }

  return (
    <main className="page-shell">
      <section className="profile-page glass-panel reveal is-visible">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Профиль</span>
            <h1>{profile?.username || "Аккаунт"}</h1>
          </div>
          <UserCircle size={30} />
        </div>
        <div className="profile-grid">
          <form className="dwd-card profile-form" onSubmit={handleProfileSubmit}>
            <div className="panel-title">
              <UserCircle size={20} />
              <h3>Данные аккаунта</h3>
            </div>
            <label>
              <span>Никнейм</span>
              <input
                value={profileForm.username}
                onChange={(event) => setProfileForm({ ...profileForm, username: event.target.value })}
                required
              />
            </label>
            <label>
              <span>Email</span>
              <input
                type="email"
                value={profileForm.email}
                onChange={(event) => setProfileForm({ ...profileForm, email: event.target.value })}
                required
              />
            </label>
            <div className="profile-meta">
              <StatusPill value={profile?.is_staff ? "admin" : "user"} />
              {profile?.groups?.map((group) => <StatusPill key={group} value={group} />)}
            </div>
            <button className="primary-button" type="submit" disabled={loading}>
              {loading ? <RefreshCw className="spin" size={18} /> : <CheckCircle2 size={18} />}
              Сохранить профиль
            </button>
          </form>

          <form className="dwd-card profile-form" onSubmit={handlePasswordSubmit}>
            <div className="panel-title">
              <Lock size={20} />
              <h3>Смена пароля</h3>
            </div>
            <label>
              <span>Текущий пароль</span>
              <input
                type="password"
                value={passwordForm.current_password}
                onChange={(event) => setPasswordForm({ ...passwordForm, current_password: event.target.value })}
                required
              />
            </label>
            <label>
              <span>Новый пароль</span>
              <input
                type="password"
                minLength={8}
                value={passwordForm.new_password}
                onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })}
                required
              />
            </label>
            <button className="primary-button" type="submit" disabled={loading}>
              {loading ? <RefreshCw className="spin" size={18} /> : <ShieldCheck size={18} />}
              Изменить пароль
            </button>
          </form>

          <article className="dwd-card profile-form">
            <div className="panel-title">
              <ShieldCheck size={20} />
              <h3>Telegram 2FA</h3>
            </div>
            <p className="empty-state">
              Бот для привязки:{" "}
              <a href={telegram2FAForm.telegram_bot_url} target="_blank" rel="noreferrer">
                {telegram2FAForm.telegram_bot_username} <ExternalLink size={14} />
              </a>
              . После нажатия “Получить код” напишите боту любое сообщение, и код придёт в Telegram.
            </p>
            <form className="profile-form nested-form" onSubmit={handleTelegram2FAStart}>
              <label>
                <span>Telegram username</span>
                <input
                  value={telegram2FAForm.telegram_username}
                  onChange={(event) => setTelegram2FAForm({ ...telegram2FAForm, telegram_username: event.target.value })}
                  placeholder="@username"
                  required
                />
              </label>
              <button className="primary-button" type="submit" disabled={loading}>
                {loading ? <RefreshCw className="spin" size={18} /> : <Send size={18} />}
                Получить код у бота
              </button>
            </form>
            <form className="profile-form nested-form" onSubmit={handleTelegram2FAVerify}>
              <label>
                <span>Код из Telegram</span>
                <input
                  value={telegram2FAForm.code}
                  onChange={(event) => setTelegram2FAForm({ ...telegram2FAForm, code: event.target.value })}
                  placeholder="123456"
                  inputMode="numeric"
                  required
                />
              </label>
              <button className="icon-text-button" type="submit" disabled={loading || !telegram2FAForm.telegram_username}>
                <ShieldCheck size={16} />
                Привязать Telegram
              </button>
            </form>
            <form className="profile-form nested-form" onSubmit={handleTelegram2FASettingsSubmit}>
              <label>
                <span>Запрашивать код</span>
                <select
                  value={telegram2FAForm.frequency}
                  onChange={(event) => setTelegram2FAForm({ ...telegram2FAForm, frequency: event.target.value })}
                >
                  <option value="always">при каждом входе</option>
                  <option value="week">раз в неделю</option>
                  <option value="month">раз в месяц</option>
                  <option value="year">раз в год</option>
                </select>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={telegram2FAForm.is_enabled}
                  disabled={!telegram2FAForm.is_linked}
                  onChange={(event) => setTelegram2FAForm({ ...telegram2FAForm, is_enabled: event.target.checked })}
                />
                <span>2FA включена</span>
              </label>
              <button className="primary-button" type="submit" disabled={loading || !telegram2FAForm.is_linked}>
                Сохранить 2FA
              </button>
            </form>
            <div className="profile-meta">
              <StatusPill value={telegram2FAForm.is_linked ? "telegram_linked" : "telegram_not_linked"} />
              <StatusPill value={telegram2FAForm.is_enabled ? "enabled" : "disabled"} />
            </div>
          </article>

          <article className="dwd-card profile-form danger-zone">
            <div className="panel-title">
              <Lock size={20} />
              <h3>Удаление аккаунта</h3>
            </div>
            <p className="empty-state">Аккаунт, заявки и связанные DWD-данные будут удалены. Действие нельзя отменить.</p>
            <button className="danger-button" type="button" disabled={loading} onClick={handleDeleteAccount}>
              Удалить аккаунт
            </button>
          </article>
        </div>
      </section>
    </main>
  );
}

function AdminPanelPage({
  isAuthenticated,
  isDwdAdmin,
  pathname,
  users,
  applications,
  devices,
  provisioningRecords,
  events,
  stationRequests,
  aiOutfits,
  iotConfig,
  iotStatus,
  iotConfigForm,
  provisioningForm,
  notifications,
  messagesByApplication,
  chatDrafts,
  supportTickets,
  supportMessages,
  supportDrafts,
  loading,
  loadDwd,
  onRoleChange,
  onUserDelete,
  onApprove,
  onReject,
  onApplicationNote,
  onDevicePatch,
  onDeviceAction,
  onPrepareProvisioning,
  onProvisioningFieldChange,
  onProvisioningSubmit,
  onProvisioningSent,
  onIotConfigFieldChange,
  onIotConfigSubmit,
  onNotificationRead,
  onChatDraftChange,
  onSupportMessageSubmit,
  onSupportDraftChange,
  onSupportTicketMessageSubmit,
  onSupportTicketStatus,
  onAiOutfitRegenerate,
  navigate,
}) {
  const adminSections = [
    ["users", "Пользователи и роли"],
    ["applications", "Заявки"],
    ["provisioning", "Прошивка"],
    ["devices", "Устройства"],
    ["events", "События устройств"],
    ["console", "Консоль"],
    ["ai-outfits", "AI советы"],
    ["support", "Техподдержка"],
    ["dwd-chat", "DWD чат"],
  ];
  const currentSection = pathname.includes("/admin-panel/instructions")
    ? "provisioning"
    : adminSections.find(([key]) => pathname.includes(`/admin-panel/${key}`))?.[0]
    || (pathname.includes("/admin-panel/serial") ? "console" : "users");
  const selectedApplicationId = pathname.match(/\/admin-panel\/applications\/(\d+)/)?.[1];
  const selectedDwdChatId = pathname.match(/\/admin-panel\/dwd-chat\/(\d+)/)?.[1];
  const selectedSupportTicketId = pathname.match(/\/admin-panel\/support\/(\d+)/)?.[1];
  const selectedDeviceId = pathname.match(/\/admin-panel\/devices\/(\d+)/)?.[1];

  function renderSection() {
    if (currentSection === "users") {
      return <AdminUsersPage users={users} loading={loading} onRoleChange={onRoleChange} onUserDelete={onUserDelete} />;
    }
    if (currentSection === "applications") {
      return (
        <AdminApplicationsPage
          applications={applications}
          selectedApplicationId={selectedApplicationId}
          loading={loading}
          onApprove={onApprove}
          onReject={onReject}
          onApplicationNote={onApplicationNote}
          onPrepareProvisioning={onPrepareProvisioning}
          notifications={notifications}
          messagesByApplication={messagesByApplication}
          chatDrafts={chatDrafts}
          onNotificationRead={onNotificationRead}
          onChatDraftChange={onChatDraftChange}
          onSupportMessageSubmit={onSupportMessageSubmit}
          navigate={navigate}
        />
      );
    }
    if (currentSection === "provisioning") {
      return (
        <AdminProvisioningPage
          applications={applications}
          provisioningRecords={provisioningRecords}
          provisioningForm={provisioningForm}
          loading={loading}
          onApprove={onApprove}
          onReject={onReject}
          onPrepareProvisioning={onPrepareProvisioning}
          onProvisioningFieldChange={onProvisioningFieldChange}
          onProvisioningSubmit={onProvisioningSubmit}
          onProvisioningSent={onProvisioningSent}
          navigate={navigate}
        />
      );
    }
    if (currentSection === "devices") {
      return (
        <AdminDevicesPage
          devices={devices}
          selectedDeviceId={selectedDeviceId}
          events={events}
          loading={loading}
          onDevicePatch={onDevicePatch}
          onDeviceAction={onDeviceAction}
          navigate={navigate}
        />
      );
    }
    if (currentSection === "events") {
      return <AdminDeviceEventsPage events={events} devices={devices} />;
    }
    if (currentSection === "console") {
      return (
        <AdminStationConsolePage
          iotStatus={iotStatus}
          stationRequests={stationRequests}
        />
      );
    }
    if (currentSection === "ai-outfits") {
      return (
        <AdminAiOutfitsPage
          records={aiOutfits}
          loading={loading}
          onRegenerate={onAiOutfitRegenerate}
        />
      );
    }
    if (currentSection === "support") {
      return (
        <AdminSupportPage
          tickets={supportTickets}
          selectedTicketId={selectedSupportTicketId}
          messagesByTicket={supportMessages}
          drafts={supportDrafts}
          loading={loading}
          onDraftChange={onSupportDraftChange}
          onSend={onSupportTicketMessageSubmit}
          onStatusChange={onSupportTicketStatus}
          navigate={navigate}
        />
      );
    }
    if (currentSection === "dwd-chat") {
      return (
        <AdminDwdChatsPage
          applications={applications}
          selectedApplicationId={selectedDwdChatId}
          messagesByApplication={messagesByApplication}
          chatDrafts={chatDrafts}
          loading={loading}
          onChatDraftChange={onChatDraftChange}
          onSupportMessageSubmit={onSupportMessageSubmit}
          navigate={navigate}
        />
      );
    }
    return (
      <AdminProvisioningPage
        applications={applications}
        provisioningRecords={provisioningRecords}
        provisioningForm={provisioningForm}
        loading={loading}
        onApprove={onApprove}
        onReject={onReject}
        onPrepareProvisioning={onPrepareProvisioning}
        onProvisioningFieldChange={onProvisioningFieldChange}
        onProvisioningSubmit={onProvisioningSubmit}
        onProvisioningSent={onProvisioningSent}
        navigate={navigate}
      />
    );
  }

  return (
    <main className="page-shell">
      <section className="admin-page glass-panel reveal is-visible">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Админка</span>
            <h1>Управление DWD</h1>
          </div>
          {isAuthenticated && (
            <button className="icon-button" onClick={() => loadDwd()} title="Обновить данные админки">
              {loading ? <RefreshCw className="spin" size={18} /> : <RefreshCw size={18} />}
            </button>
          )}
        </div>
        {!isAuthenticated ? (
          <AccessGate navigate={navigate} text="Войдите как admin, чтобы открыть эту страницу." />
        ) : !isDwdAdmin ? (
          <div className="access-gate">
            <div className="panel-title">
              <Lock size={20} />
              <h2>Только для admin</h2>
            </div>
            <p>У вашего аккаунта нет прав admin.</p>
          </div>
        ) : (
          <>
            <nav className="admin-tabs" aria-label="DWD admin sections">
              {adminSections.map(([key, label]) => (
                <button
                  key={key}
                  className={currentSection === key ? "active" : ""}
                  type="button"
                  onClick={() => navigate(`/admin-panel/${key}`)}
                >
                  {label}
                </button>
              ))}
            </nav>
            {renderSection()}
          </>
        )}
      </section>
    </main>
  );
}

function AdminUsersPage({ users, loading, onRoleChange, onUserDelete }) {
  return (
    <AdminTableCard title="Пользователи и роли" icon={<UserCircle size={20} />}>
      <div className="admin-table">
        <div className="admin-row admin-row-head">
          <span>ID</span><span>Пользователь</span><span>Email</span><span>Роль</span><span>Заявка</span><span>Устройства</span><span>Действия</span>
        </div>
        {users.map((user) => (
          <div className="admin-row" key={user.id}>
            <span>{user.id}</span>
            <span>{user.username}</span>
            <span>{user.email || "нет"}</span>
            <span>
              <select value={user.role} disabled={loading} onChange={(event) => onRoleChange(user.id, event.target.value)}>
                <option value="user">user</option>
                <option value="provider">provider</option>
                <option value="admin">admin</option>
              </select>
            </span>
            <span>{user.active_application ? `${statusLabel(user.active_application.status)} / ${user.active_application.city}` : "нет"}</span>
            <span>{user.device_count}</span>
            <span><button className="danger-button compact-danger" type="button" disabled={loading} onClick={() => onUserDelete(user.id)}>Удалить</button></span>
          </div>
        ))}
      </div>
    </AdminTableCard>
  );
}

function AdminApplicationsPage({
  applications,
  selectedApplicationId,
  loading,
  onApprove,
  onReject,
  onApplicationNote,
  onPrepareProvisioning,
  notifications,
  messagesByApplication,
  chatDrafts,
  onNotificationRead,
  onChatDraftChange,
  onSupportMessageSubmit,
  navigate,
}) {
  const selected = applications.find((item) => String(item.id) === String(selectedApplicationId));
  return (
    <div className="admin-page-grid">
      <NotificationsPanel notifications={notifications} onRead={onNotificationRead} />
      <AdminTableCard title="Заявки DWD provider" icon={<FileText size={20} />}>
        <div className="admin-table admin-table-applications">
          <div className="admin-row admin-row-head">
            <span>ID</span><span>Пользователь</span><span>Email для связи</span><span>Город</span><span>Статус</span><span>Проверка</span><span>Действия</span>
          </div>
          {applications.map((application) => (
            <div className="admin-row" key={application.id}>
              <span>{application.id}</span>
              <span>{application.user?.username}</span>
              <span>{application.email}</span>
              <span>{application.city}</span>
              <span><StatusPill value={application.status} /></span>
              <span>{application.reviewed_by ? `${application.reviewed_by.username} / ${formatDate(application.reviewed_at)}` : "не проверена"}</span>
              <span className="row-actions">
                <button className="icon-text-button" type="button" onClick={() => navigate(`/admin-panel/applications/${application.id}`)}>Открыть</button>
                <button className="icon-text-button" type="button" onClick={() => navigate(`/admin-panel/dwd-chat/${application.id}`)}>Чат</button>
                {application.status === "pending" && <button className="icon-text-button" disabled={loading} type="button" onClick={() => onApprove(application.id)}>Одобрить</button>}
                {application.status === "pending" && <button className="icon-text-button" disabled={loading} type="button" onClick={() => onReject(application.id)}>Отклонить</button>}
              </span>
            </div>
          ))}
        </div>
      </AdminTableCard>
      {selected && (
        <ApplicationDetailCard
          application={selected}
          loading={loading}
          onApprove={onApprove}
          onReject={onReject}
          onApplicationNote={onApplicationNote}
          onPrepareProvisioning={onPrepareProvisioning}
          messages={messagesByApplication[selected.id] || []}
          chatDraft={chatDrafts[selected.id] || ""}
          onChatDraftChange={onChatDraftChange}
          onSupportMessageSubmit={onSupportMessageSubmit}
        />
      )}
    </div>
  );
}

function ApplicationDetailCard({
  application,
  loading,
  onApprove,
  onReject,
  onApplicationNote,
  onPrepareProvisioning,
  messages,
  chatDraft,
  onChatDraftChange,
  onSupportMessageSubmit,
}) {
  const [note, setNote] = useState(application.admin_note || "");
  useEffect(() => setNote(application.admin_note || ""), [application.id, application.admin_note]);
  return (
    <article className="dwd-card detail-card">
      <div className="panel-title"><FileText size={20} /><h3>Заявка #{application.id}</h3></div>
      <div className="detail-grid">
        <Metric icon={<UserCircle size={18} />} label="Пользователь" value={formatUser(application.user)} />
        <Metric icon={<MapPin size={18} />} label="Город" value={application.city} />
        <Metric icon={<Send size={18} />} label="Email" value={application.email} />
        <Metric icon={<Activity size={18} />} label="Статус" value={statusLabel(application.status)} />
        <Metric icon={<FileText size={18} />} label="Создана" value={formatDate(application.created_at)} />
        <Metric icon={<ShieldCheck size={18} />} label="Проверка" value={application.reviewed_by ? `${application.reviewed_by.username} / ${formatDate(application.reviewed_at)}` : "не проверена"} />
      </div>
      <p className="empty-state">{application.comment}</p>
      <div className="row-actions">
        {application.status === "pending" && <button className="primary-button compact-action" disabled={loading} type="button" onClick={() => onApprove(application.id)}>Одобрить заявку</button>}
        {application.status === "pending" && <button className="danger-button compact-danger" disabled={loading} type="button" onClick={() => onReject(application.id)}>Отклонить заявку</button>}
      </div>
      {application.device && <DeviceSummary device={application.device} />}
      <SupportChat
        application={application}
        messages={messages}
        draft={chatDraft}
        loading={loading}
        onDraftChange={onChatDraftChange}
        onSend={onSupportMessageSubmit}
        title="Чат с провайдером"
      />
      <label>
        <span>Заметка админа</span>
        <textarea value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      <div className="row-actions">
        <button className="primary-button" type="button" disabled={loading} onClick={() => onApplicationNote(application.id, note)}>Сохранить заметку</button>
      </div>
    </article>
  );
}

function AdminProvisioningPage({
  applications,
  provisioningRecords,
  provisioningForm,
  loading,
  onApprove,
  onReject,
  onPrepareProvisioning,
  onProvisioningFieldChange,
  onProvisioningSubmit,
  onProvisioningSent,
  navigate,
}) {
  return (
    <div className="admin-page-grid">
      <AdminTableCard title="Заявки и решение" icon={<Radio size={20} />}>
        <p className="empty-state">Здесь админ принимает решение по заявке. После одобрения провайдер сам соберёт прошивку в личном кабинете.</p>
        <div className="admin-table admin-table-applications">
          <div className="admin-row admin-row-head">
            <span>ID</span><span>Пользователь</span><span>Email для связи</span><span>Город</span><span>Комментарий</span><span>Статус</span><span>Действия</span>
          </div>
          {applications.map((application) => (
            <div className="admin-row" key={application.id}>
              <span>{application.id}</span>
              <span>{application.user?.username}</span>
              <span>{application.email}</span>
              <span>{application.city}</span>
              <span>{application.comment}</span>
              <span><StatusPill value={application.status} /></span>
              <span className="row-actions">
                <button className="icon-text-button" type="button" onClick={() => navigate(`/admin-panel/applications/${application.id}`)}>Открыть</button>
                <button className="icon-text-button" type="button" onClick={() => navigate(`/admin-panel/dwd-chat/${application.id}`)}>Чат</button>
                {application.status === "pending" && <button className="primary-button compact-action" disabled={loading} type="button" onClick={() => onApprove(application.id)}>Одобрить</button>}
                {application.status === "pending" && <button className="danger-button compact-danger" disabled={loading} type="button" onClick={() => onReject(application.id)}>Отклонить</button>}
              </span>
            </div>
          ))}
        </div>
      </AdminTableCard>

      <AdminTableCard title="Коды, сгенерированные провайдерами" icon={<Send size={20} />}>
        <p className="empty-state">
          Провайдер сам заполняет параметры прошивки в личном кабинете. Системные ключи, station ID и MQTT topic подставляет backend.
        </p>
        <ProvisioningList records={provisioningRecords} loading={loading} onProvisioningSent={onProvisioningSent} showInstruction allowMarkSent={false} />
      </AdminTableCard>
    </div>
  );
}

function AdminDwdChatsPage({ applications, selectedApplicationId, messagesByApplication, chatDrafts, loading, onChatDraftChange, onSupportMessageSubmit, navigate }) {
  const selected = applications.find((item) => String(item.id) === String(selectedApplicationId)) || applications[0] || null;
  return (
    <div className="admin-page-grid">
      <AdminTableCard title="DWD чат по заявкам" icon={<MessageCircle size={20} />}>
        <div className="admin-table admin-table-applications">
          <div className="admin-row admin-row-head">
            <span>ID</span><span>Пользователь</span><span>Email</span><span>Город</span><span>Статус</span><span>Последнее</span><span>Действие</span>
          </div>
          {applications.map((application) => {
            const messages = messagesByApplication[application.id] || [];
            const last = messages[messages.length - 1];
            return (
              <div className="admin-row" key={application.id}>
                <span>{application.id}</span>
                <span>{application.user?.username}</span>
                <span>{application.email}</span>
                <span>{application.city}</span>
                <span><StatusPill value={application.status} /></span>
                <span>{last ? `${last.sender?.username || "Система"}: ${last.message}` : "нет сообщений"}</span>
                <span><button className="icon-text-button" type="button" onClick={() => navigate(`/admin-panel/dwd-chat/${application.id}`)}>Открыть чат</button></span>
              </div>
            );
          })}
        </div>
      </AdminTableCard>
      {selected && (
        <SupportChat
          application={selected}
          messages={messagesByApplication[selected.id] || []}
          draft={chatDrafts[selected.id] || ""}
          loading={loading}
          onDraftChange={onChatDraftChange}
          onSend={onSupportMessageSubmit}
          title={`DWD чат: ${selected.city}`}
        />
      )}
    </div>
  );
}

function AdminSupportPage({
  tickets = [],
  selectedTicketId,
  messagesByTicket = {},
  drafts = {},
  loading,
  onDraftChange = () => {},
  onSend = () => {},
  onStatusChange = () => {},
  navigate,
}) {
  const selected = tickets.find((ticket) => String(ticket.id) === String(selectedTicketId)) || tickets[0] || null;
  return (
    <div className="admin-page-grid">
      <AdminTableCard title="Техническая поддержка" icon={<MessageCircle size={20} />}>
        <div className="admin-table admin-table-support">
          <div className="admin-row admin-row-head">
            <span>ID</span><span>Пользователь</span><span>Тема</span><span>Категория</span><span>Статус</span><span>Обновлён</span><span>Действие</span>
          </div>
          {tickets.map((ticket) => (
            <div className="admin-row" key={ticket.id}>
              <span>{ticket.id}</span>
              <span>{formatUser(ticket.requester)}</span>
              <span>{ticket.subject}</span>
              <span>{ticket.category}</span>
              <span><StatusPill value={ticket.status} /></span>
              <span>{formatDate(ticket.updated_at)}</span>
              <span><button className="icon-text-button" type="button" onClick={() => navigate(`/admin-panel/support/${ticket.id}`)}>Открыть</button></span>
            </div>
          ))}
        </div>
        {!tickets.length && <p className="empty-state">Обращений в техподдержку пока нет.</p>}
      </AdminTableCard>
      {selected && (
        <article className="dwd-card support-chat">
          <div className="panel-title"><MessageCircle size={20} /><h3>{selected.subject}</h3></div>
          <div className="detail-grid">
            <Metric icon={<UserCircle size={18} />} label="Пользователь" value={formatUser(selected.requester)} />
            <Metric icon={<Activity size={18} />} label="Статус" value={statusLabel(selected.status)} />
            <Metric icon={<FileText size={18} />} label="Категория" value={selected.category} />
          </div>
          <label>
            <span>Статус тикета</span>
            <select value={selected.status} onChange={(event) => onStatusChange(selected.id, event.target.value)}>
              <option value="open">open</option>
              <option value="in_progress">in_progress</option>
              <option value="resolved">resolved</option>
              <option value="closed">closed</option>
            </select>
          </label>
          <div className="chat-thread">
            {(messagesByTicket[selected.id] || []).map((message) => (
              <div className={`chat-message ${message.is_system ? "is-system" : ""}`} key={message.id}>
                <strong>{message.is_system ? "Система" : (message.sender?.username || "Пользователь")}</strong>
                <p>{message.message}</p>
                <small>{formatDate(message.created_at)}</small>
              </div>
            ))}
          </div>
          <form className="chat-form" onSubmit={(event) => { event.preventDefault(); onSend(selected.id); }}>
            <input value={drafts[selected.id] || ""} onChange={(event) => onDraftChange(selected.id, event.target.value)} placeholder="Ответить пользователю" />
            <button className="primary-button" type="submit" disabled={loading || !(drafts[selected.id] || "").trim()}>
              <Send size={16} />
              Отправить
            </button>
          </form>
        </article>
      )}
    </div>
  );
}

function AdminDevicesPage({ devices, selectedDeviceId, events, loading, onDevicePatch, onDeviceAction, navigate }) {
  const selected = devices.find((item) => String(item.id) === String(selectedDeviceId));
  return (
    <div className="admin-page-grid">
    <AdminTableCard title="Устройства" icon={<Cpu size={20} />}>
        <div className="admin-table admin-table-devices">
          <div className="admin-row admin-row-head">
            <span>Код</span><span>Владелец</span><span>Email</span><span>Город</span><span>Прошивка</span><span>Статус</span><span>Онлайн</span><span>Последние данные</span><span>Действие</span>
          </div>
          {devices.map((device) => (
            <div className="admin-row" key={device.id}>
              <span>{device.device_code || device.station_id}</span><span>{device.owner?.username}</span><span>{device.owner_email}</span><span>{device.city}</span><span>{device.firmware_type || "нет"} {device.firmware_version}</span><span>{statusLabel(device.status)}</span><span>{statusLabel(device.online_status)}</span><span>{formatDate(device.last_data_at)}</span>
              <span><button className="icon-text-button" type="button" onClick={() => navigate(`/admin-panel/devices/${device.id}`)}>Открыть</button></span>
            </div>
          ))}
        </div>
      </AdminTableCard>
      {selected && <DeviceDetailCard device={selected} events={events.filter((event) => event.device === selected.id)} loading={loading} onDevicePatch={onDevicePatch} onDeviceAction={onDeviceAction} />}
    </div>
  );
}

function DeviceDetailCard({ device, events, loading, onDevicePatch, onDeviceAction }) {
  const [metadata, setMetadata] = useState({
    device_code: device.device_code || "",
    station_id: device.station_id || "",
    city: device.city || "",
    firmware_type: device.firmware_type || "",
    firmware_version: device.firmware_version || "",
    ip_address: device.ip_address || "",
    status: device.status || "inactive",
    is_enabled: Boolean(device.is_enabled),
    notes: device.notes || "",
  });
  useEffect(() => {
    setMetadata({
      device_code: device.device_code || "",
      station_id: device.station_id || "",
      city: device.city || "",
      firmware_type: device.firmware_type || "",
      firmware_version: device.firmware_version || "",
      ip_address: device.ip_address || "",
      status: device.status || "inactive",
      is_enabled: Boolean(device.is_enabled),
      notes: device.notes || "",
    });
  }, [device.id, device.device_code, device.station_id, device.city, device.firmware_type, device.firmware_version, device.ip_address, device.status, device.is_enabled, device.notes]);

  function updateMetadata(field, value) {
    setMetadata((current) => ({ ...current, [field]: value }));
  }

  function saveMetadata() {
    onDevicePatch(device.id, {
      device_code: metadata.device_code.trim() || null,
      station_id: metadata.station_id.trim(),
      city: metadata.city.trim(),
      firmware_type: metadata.firmware_type.trim(),
      firmware_version: metadata.firmware_version.trim(),
      ip_address: metadata.ip_address.trim() || null,
      status: metadata.status,
      is_enabled: Boolean(metadata.is_enabled),
      notes: metadata.notes,
    });
  }

  return (
    <article className="dwd-card detail-card">
      <div className="panel-title"><Cpu size={20} /><h3>{device.device_code || device.station_id}</h3></div>
      <div className="detail-grid">
        <Metric icon={<UserCircle size={18} />} label="Владелец" value={`${device.owner?.username} / ${device.owner_email}`} />
        <Metric icon={<MapPin size={18} />} label="Город" value={device.city} />
        <Metric icon={<Radio size={18} />} label="Прошивка" value={`${device.firmware_type || "нет"} ${device.firmware_version || ""}`} />
        <Metric icon={<Activity size={18} />} label="Онлайн" value={statusLabel(device.online_status)} />
        <Metric icon={<Activity size={18} />} label="IP" value={device.ip_address || "нет"} />
        <Metric icon={<FileText size={18} />} label="Token" value={device.token_masked || "нет"} />
        <Metric icon={<RefreshCw size={18} />} label="Последний heartbeat" value={formatDate(device.last_seen_at)} />
        <Metric icon={<RefreshCw size={18} />} label="Последний запрос" value={formatDate(device.last_request_at)} />
        <Metric icon={<RefreshCw size={18} />} label="Последние данные" value={formatDate(device.last_data_at)} />
        <Metric icon={<Lock size={18} />} label="Статус" value={`${statusLabel(device.status)} / ${device.is_enabled ? "включено" : "выключено"}`} />
        <Metric icon={<Send size={18} />} label="Инструкция" value={device.instruction_sent ? `отправлена ${formatDate(device.instruction_sent_at)}` : statusLabel(device.provisioning_status || "not_started")} />
        <Metric icon={<FileText size={18} />} label="Последняя ошибка" value={device.last_error || "нет"} />
      </div>
      <form className="dwd-form compact-form device-edit-form" onSubmit={(event) => { event.preventDefault(); saveMetadata(); }}>
        <label>
          <span>Название / device code</span>
          <input value={metadata.device_code} onChange={(event) => updateMetadata("device_code", event.target.value)} placeholder="DWD Saransk Station" />
        </label>
        <label>
          <span>Station ID</span>
          <input value={metadata.station_id} onChange={(event) => updateMetadata("station_id", event.target.value)} placeholder="DWD-SARANSK-001" required />
        </label>
        <label>
          <span>Город</span>
          <input value={metadata.city} onChange={(event) => updateMetadata("city", event.target.value)} placeholder="Saransk" required />
        </label>
        <label>
          <span>IP address</span>
          <input value={metadata.ip_address} onChange={(event) => updateMetadata("ip_address", event.target.value)} placeholder="опционально" />
        </label>
        <label>
          <span>Firmware type</span>
          <select value={metadata.firmware_type} onChange={(event) => updateMetadata("firmware_type", event.target.value)}>
            <option value="">не выбрано</option>
            <option value="serial_bridge">serial_bridge</option>
            <option value="esp01_wifi">esp01_wifi</option>
            <option value="ethernet_shield">ethernet_shield</option>
          </select>
        </label>
        <label>
          <span>Firmware version</span>
          <input value={metadata.firmware_version} onChange={(event) => updateMetadata("firmware_version", event.target.value)} placeholder="1.0.0" />
        </label>
        <label>
          <span>Статус</span>
          <select value={metadata.status} onChange={(event) => updateMetadata("status", event.target.value)}>
            <option value="inactive">inactive</option>
            <option value="active">active</option>
            <option value="blocked">blocked</option>
          </select>
        </label>
        <label className="checkbox-row serial-enabled-row">
          <input type="checkbox" checked={metadata.is_enabled} onChange={(event) => updateMetadata("is_enabled", event.target.checked)} />
          <span>Устройство включено</span>
        </label>
        <label className="wide-field">
          <span>Заметки по устройству</span>
          <textarea value={metadata.notes} onChange={(event) => updateMetadata("notes", event.target.value)} />
        </label>
        <button className="primary-button" type="submit" disabled={loading}>Сохранить станцию</button>
      </form>
      <div className="row-actions">
        <button className="icon-text-button" type="button" disabled={loading} onClick={() => onDeviceAction(device.id, "enable")}>Включить</button>
        <button className="icon-text-button" type="button" disabled={loading} onClick={() => onDeviceAction(device.id, "disable")}>Выключить</button>
        <button className="danger-button compact-danger" type="button" disabled={loading} onClick={() => onDeviceAction(device.id, "block")}>Заблокировать</button>
      </div>
      <DeviceEventsList events={events} />
    </article>
  );
}

function AdminDeviceEventsPage({ events, devices }) {
  return (
    <AdminTableCard title="События устройств / мониторинг" icon={<Activity size={20} />}>
      <DeviceEventsList events={events} devices={devices} />
    </AdminTableCard>
  );
}

function AdminStationConsolePage({ iotStatus, stationRequests = [] }) {
  const mqtt = iotStatus?.mqtt || {};
  const acceptedCount = stationRequests.filter((request) => request.accepted).length;
  const errorCount = stationRequests.length - acceptedCount;
  const latestRequest = stationRequests[0] || null;

  return (
    <div className="admin-page-grid">
      <AdminTableCard title="Консоль станций" icon={<Terminal size={20} />}>
        <div className="detail-grid serial-status-grid">
          <Metric icon={<Activity size={18} />} label="Всего записей" value={stationRequests.length} />
          <Metric icon={<CheckCircle2 size={18} />} label="Успешно" value={acceptedCount} />
          <Metric icon={<ShieldCheck size={18} />} label="С ошибкой" value={errorCount} />
          <Metric icon={<RefreshCw size={18} />} label="Последний запрос" value={formatDate(latestRequest?.created_at)} />
          <Metric icon={<Radio size={18} />} label="MQTT" value={statusLabel(mqtt.broker_status || mqtt.status || "unknown")} />
          <Metric icon={<Waves size={18} />} label="Последнее MQTT-сообщение" value={formatDate(mqtt.last_seen)} />
        </div>
        <p className="empty-state console-note">
          Здесь отображаются входящие сообщения от физических станций: HTTP и MQTT. USB-подключение к серверу не требуется.
        </p>
      </AdminTableCard>

      <AdminTableCard title="Последние сообщения" icon={<Activity size={20} />}>
        <StationRequestsTable requests={stationRequests} />
      </AdminTableCard>
    </div>
  );
}

function StationRequestsTable({ requests = [] }) {
  if (!requests.length) {
    return (
      <div className="serial-terminal-empty">
        <Activity size={20} />
        <span>Пока нет сообщений от станций. Когда устройство отправит HTTP или MQTT-измерение, оно появится здесь.</span>
      </div>
    );
  }

  return (
    <div className="admin-table admin-table-station-requests">
      <div className="admin-row admin-row-head">
        <span>Время</span><span>Станция</span><span>Город</span><span>Канал</span><span>Статус</span><span>IP</span><span>Запрос</span><span>Ошибка</span>
      </div>
      {requests.map((request) => {
        const stationName = request.station?.name || request.station_name || request.station_id || "—";
        const city = request.station?.city || request.city || "—";
        const source = request.source || request.raw_payload?.source || request.raw_payload?.payload?.source || "http";
        const requestSummary = formatStationRequestSummary(request);
        return (
          <div className="admin-row" key={request.id}>
            <span>{formatDate(request.created_at)}</span>
            <span>
              <strong>{stationName}</strong>
              <small>{request.station_id}</small>
            </span>
            <span>{city}</span>
            <span>{statusLabel(source)}</span>
            <span><StatusPill value={request.accepted ? "online" : "error"} /></span>
            <span>
              {request.request_ip || "—"}
              {request.request_latency_ms !== null && request.request_latency_ms !== undefined && (
                <small>{request.request_latency_ms} ms</small>
              )}
            </span>
            <span><code>{requestSummary}</code></span>
            <span>{request.error || "—"}</span>
          </div>
        );
      })}
    </div>
  );
}

function AdminAiOutfitsPage({ records = [], loading, onRegenerate }) {
  const [cityFilter, setCityFilter] = useState("");
  const normalizedFilter = cityFilter.trim().toLowerCase();
  const visibleRecords = normalizedFilter
    ? records.filter((record) => String(record.city || "").toLowerCase().includes(normalizedFilter))
    : records;

  return (
    <AdminTableCard title="AI советы по городам" icon={<Sparkles size={20} />}>
      <p className="empty-state">
        Здесь видны сохранённые советы по одежде. Если LLM выдала странный текст, перегенерируйте конкретную запись.
      </p>
      <label className="wide-field">
        <span>Фильтр по городу</span>
        <input
          value={cityFilter}
          onChange={(event) => setCityFilter(event.target.value)}
          placeholder="Например, Саранск"
        />
      </label>
      {visibleRecords.length ? (
        <div className="dwd-list ai-outfit-admin-list">
          {visibleRecords.map((record) => (
            <div className="dwd-list-item" key={record.id}>
              <div>
                <strong>{record.city}</strong>
                <small>
                  {formatDate(record.hour_bucket)} / {formatNumber(record.temperature_c)} °C / ветер {formatNumber(record.wind_speed_ms)} m/s / осадки {formatNumber(record.precipitation_mm)} mm
                </small>
                <small>Модель: {record.model || "не указана"} / prompt {record.prompt_version}</small>
                <p>{cleanRecommendationText(record.recommendation)}</p>
              </div>
              <div className="row-actions">
                <button
                  className="icon-text-button"
                  type="button"
                  disabled={loading}
                  onClick={() => onRegenerate(record.id)}
                >
                  {loading ? <RefreshCw className="spin" size={16} /> : <Sparkles size={16} />}
                  Перегенерировать
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-state">AI-советов пока нет или фильтр ничего не нашёл.</p>
      )}
    </AdminTableCard>
  );
}

function formatStationRequestSummary(request) {
  const temperature = request.temperature_c ?? request.raw_payload?.temperature_c ?? request.raw_payload?.payload?.temperature_c;
  const humidity = request.humidity ?? request.raw_payload?.humidity ?? request.raw_payload?.payload?.humidity;
  const parts = [];
  if (temperature !== null && temperature !== undefined) {
    parts.push(`temp=${formatNumber(temperature)}°C`);
  }
  if (humidity !== null && humidity !== undefined) {
    parts.push(`humidity=${formatNumber(humidity, 0)}%`);
  }
  if (request.status_code) {
    parts.push(`status=${request.status_code}`);
  }
  if (parts.length) return parts.join("; ");
  return JSON.stringify(request.raw_payload || {});
}

function AdminInstructionsPage({
  applications,
  provisioningRecords,
  provisioningForm,
  loading,
  onPrepareProvisioning,
  onProvisioningFieldChange,
  onProvisioningSubmit,
  onProvisioningSent,
}) {
  return (
    <AdminTableCard title="Автогенерация прошивки" icon={<Send size={20} />}>
      <ProvisioningForm
        applications={applications}
        provisioningForm={provisioningForm}
        loading={loading}
        onPrepareProvisioning={onPrepareProvisioning}
        onProvisioningFieldChange={onProvisioningFieldChange}
        onProvisioningSubmit={onProvisioningSubmit}
      />
      <ProvisioningList records={provisioningRecords} loading={loading} onProvisioningSent={onProvisioningSent} showInstruction />
    </AdminTableCard>
  );
}

function AdminTableCard({ title, icon, children }) {
  return (
    <article className="dwd-card admin-table-card">
      <div className="panel-title">{icon}<h3>{title}</h3></div>
      {children}
    </article>
  );
}

function DeviceSummary({ device }) {
  return (
    <div className="station-empty">
      <Cpu size={22} />
      <div>
        <strong>{device.device_code || device.station_id}</strong>
        <p>{device.city} / {statusLabel(device.status)} / {statusLabel(device.online_status || "offline")} / {device.firmware_type || "прошивка не выбрана"}</p>
      </div>
    </div>
  );
}

function ProvisioningForm({ applications, provisioningForm, loading, onPrepareProvisioning, onProvisioningFieldChange, onProvisioningSubmit }) {
  return (
    <form className="dwd-form compact-form" id="dwd-provisioning-form" onSubmit={onProvisioningSubmit}>
      <label>
        <span>Заявка</span>
        <select
          value={provisioningForm.application_id}
          onChange={(event) => {
            const application = applications.find((item) => String(item.id) === event.target.value);
            if (application) onPrepareProvisioning(application);
            else onProvisioningFieldChange("application_id", event.target.value);
          }}
          required
        >
          <option value="">Выберите одобренную заявку</option>
          {applications.filter((item) => item.status === "approved").map((application) => (
            <option key={application.id} value={application.id}>
              #{application.id} {application.city} / {application.email}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Тип прошивки</span>
        <select value={provisioningForm.firmware_type} onChange={(event) => onProvisioningFieldChange("firmware_type", event.target.value)}>
          <option value="serial_bridge">serial_bridge</option>
          <option value="esp01_wifi">MQTT Wi-Fi</option>
          <option value="ethernet_shield">ethernet_shield</option>
        </select>
      </label>
      <label>
        <span>Версия</span>
        <input value={provisioningForm.firmware_version} onChange={(event) => onProvisioningFieldChange("firmware_version", event.target.value)} placeholder="1.0.0" />
      </label>
      <label>
        <span>Канал отправки</span>
        <select value={provisioningForm.delivery_channel} onChange={(event) => onProvisioningFieldChange("delivery_channel", event.target.value)}>
          <option value="email">email</option>
          <option value="manual">вручную</option>
        </select>
      </label>
      <label className="wide-field">
        <span>Wi-Fi SSID <em>необязательно</em></span>
        <input
          value={provisioningForm.wifi_ssid}
          onChange={(event) => onProvisioningFieldChange("wifi_ssid", event.target.value)}
          placeholder="Провайдер может оставить пустым"
        />
      </label>
      <label className="wide-field">
        <span>Wi-Fi password <em>необязательно</em></span>
        <input
          type="password"
          value={provisioningForm.wifi_password}
          onChange={(event) => onProvisioningFieldChange("wifi_password", event.target.value)}
          placeholder="Если пусто, в коде останется placeholder"
        />
      </label>
      <label className="wide-field">
        <span>Комментарий к выдаче <em>необязательно</em></span>
        <textarea value={provisioningForm.instruction_text} onChange={(event) => onProvisioningFieldChange("instruction_text", event.target.value)} placeholder="Можно оставить пустым: код прошивки всё равно будет сгенерирован автоматически." />
      </label>
      <p className="empty-state wide-field">
        После сохранения backend выдаст готовый Arduino MQTT Wi-Fi код с station_id, MQTT topic и MQTT-доступом. Wi-Fi можно вписать здесь или оставить placeholders в коде.
      </p>
      <label className="wide-field">
        <span>Внутренняя заметка</span>
        <textarea value={provisioningForm.notes} onChange={(event) => onProvisioningFieldChange("notes", event.target.value)} placeholder="Видно только администратору" />
      </label>
      <button className="primary-button" type="submit" disabled={loading || !provisioningForm.application_id}>
        {loading ? <RefreshCw className="spin" size={18} /> : <FileText size={18} />}
        Сгенерировать прошивку
      </button>
    </form>
  );
}

function ProvisioningList({ records, loading, onProvisioningSent, showInstruction = false, allowMarkSent = true }) {
  return records.length ? (
    <div className="dwd-list">
      {records.map((record) => (
        <div className="dwd-list-item" key={record.id}>
          <div>
            <strong>{record.firmware_type} {record.firmware_version}</strong>
            <small>{formatUser(record.user)} / {record.device?.city || "устройство не привязано"}</small>
            <small>Статус: {statusLabel(record.delivery_status)}; сгенерировано: {formatDate(record.code_generated_at || record.updated_at)}</small>
            {showInstruction && <small>{record.instruction_text}</small>}
            {showInstruction && <FirmwareCodeBlock code={record.firmware_code} />}
          </div>
          <div className="row-actions">
            <StatusPill value={record.delivery_status} />
            {allowMarkSent && record.delivery_status !== "sent" && record.delivery_status !== "acknowledged" && (
              <button className="icon-text-button" type="button" disabled={loading} onClick={() => onProvisioningSent(record.id)}>
                <Send size={16} />
                Отправлено
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  ) : (
    <p className="empty-state">Записей provisioning пока нет.</p>
  );
}

function DeviceEventsList({ events }) {
  return events?.length ? (
    <div className="admin-table admin-table-events">
      <div className="admin-row admin-row-head">
        <span>Время</span><span>Событие</span><span>Уровень</span><span>Сообщение</span><span>IP</span>
      </div>
      {events.map((event) => (
        <div className="admin-row" key={event.id}>
          <span>{formatDate(event.created_at)}</span>
          <span>{event.event_type}</span>
          <span><StatusPill value={event.severity} /></span>
          <span>{event.message || "нет"}</span>
          <span>{event.ip_address || "нет"}</span>
        </div>
      ))}
    </div>
  ) : (
    <p className="empty-state">Событий устройства пока нет.</p>
  );
}

function formatUser(user) {
  if (!user) return "неизвестно";
  return user.email ? `${user.username} (${user.email})` : user.username;
}

function statusLabel(value) {
  const labels = {
    user: "пользователь",
    provider: "provider",
    admin: "admin",
    pending: "на рассмотрении",
    approved: "одобрена",
    rejected: "отклонена",
    cancelled: "отменена",
    inactive: "неактивно",
    active: "активно",
    enabled: "включено",
    disabled: "выключено",
    blocked: "заблокировано",
    online: "online",
    offline: "offline",
    connected: "подключено",
    disconnected: "нет подключения",
    serial_bridge: "Serial Bridge",
    wifi_esp01: "ESP-01 Wi-Fi",
    ethernet_shield: "Ethernet Shield",
    mqtt: "MQTT",
    unknown: "неизвестно",
    not_started: "не начато",
    firmware_assigned: "прошивка выбрана",
    instruction_ready: "инструкция готова",
    sent: "отправлено вручную",
    acknowledged: "подтверждено",
    info: "инфо",
    warning: "предупреждение",
    error: "ошибка",
    registered: "зарегистрировано",
    activated: "активировано",
    heartbeat: "heartbeat",
    data_ingest: "данные получены",
    auth_failed: "ошибка авторизации",
    offline_detected: "offline обнаружен",
    settings_changed: "настройки изменены",
    telegram_linked: "Telegram привязан",
    telegram_not_linked: "Telegram не привязан",
    application_submitted: "новая заявка",
    status_changed: "статус изменён",
    provisioning_ready: "прошивка готова",
    chat_message: "сообщение",
    support_ticket: "тикет",
    support_message: "сообщение поддержки",
    open: "открыт",
    in_progress: "в работе",
    resolved: "решён",
    closed: "закрыт",
    low: "низкий",
    normal: "обычный",
    high: "высокий",
  };
  return labels[value] || value || "нет";
}

function StatusPill({ value }) {
  return <span className={`status-pill status-${value || "empty"}`}>{statusLabel(value)}</span>;
}

function NotificationsPanel({ notifications = [], onRead }) {
  if (!notifications.length) return null;
  return (
    <article className="dwd-card notifications-panel">
      <div className="panel-title">
        <Bell size={20} />
        <h3>Уведомления</h3>
      </div>
      <div className="dwd-list">
        {notifications.slice(0, 6).map((notification) => (
          <div className={`dwd-list-item notification-item ${notification.is_read ? "" : "is-unread"}`} key={notification.id}>
            <div>
              <strong>{notification.title}</strong>
              <small>{notification.message || statusLabel(notification.notification_type)}</small>
              <small>{formatDate(notification.created_at)}</small>
            </div>
            {!notification.is_read && (
              <button className="icon-text-button" type="button" onClick={() => onRead(notification.id)}>
                Прочитано
              </button>
            )}
          </div>
        ))}
      </div>
    </article>
  );
}

function NotificationsDropdown({ notifications = [], onRead, navigate, isAdmin }) {
  return (
    <div className="notifications-dropdown">
      <div className="dropdown-title">
        <Bell size={16} />
        <strong>Уведомления</strong>
      </div>
      {notifications.length ? notifications.slice(0, 8).map((notification) => (
        <button
          className={`notification-row ${notification.is_read ? "" : "is-unread"}`}
          type="button"
          key={notification.id}
          onClick={() => {
            if (!notification.is_read) onRead(notification.id);
            if (notification.support_ticket_id) {
              navigate(isAdmin ? "/admin-panel/support" : "/provider");
            } else if (notification.application_id) {
              navigate(isAdmin ? `/admin-panel/applications/${notification.application_id}` : "/provider");
            }
          }}
        >
          <span>{notification.title}</span>
          <small>{notification.message || statusLabel(notification.notification_type)}</small>
        </button>
      )) : (
        <p className="empty-state">Новых уведомлений нет.</p>
      )}
    </div>
  );
}

function SupportChat({ application, messages = [], draft = "", loading, onDraftChange, onSend, title }) {
  if (!application) return null;
  return (
    <article className="dwd-card support-chat">
      <div className="panel-title">
        <MessageCircle size={20} />
        <h3>{title}</h3>
      </div>
      <div className="chat-thread">
        {messages.length ? messages.map((message) => (
          <div className={`chat-message ${message.is_system ? "is-system" : ""}`} key={message.id}>
            <strong>{message.is_system ? "Система" : (message.sender?.username || "Пользователь")}</strong>
            <p>{message.message}</p>
            <small>{formatDate(message.created_at)}</small>
          </div>
        )) : (
          <p className="empty-state">Сообщений пока нет. Здесь можно уточнить детали заявки и прошивки.</p>
        )}
      </div>
      <form
        className="chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          onSend(application.id);
        }}
      >
        <input
          value={draft}
          onChange={(event) => onDraftChange(application.id, event.target.value)}
          placeholder="Напишите сообщение"
        />
        <button className="primary-button" type="submit" disabled={loading || !draft.trim()}>
          <Send size={16} />
          Отправить
        </button>
      </form>
    </article>
  );
}

function SupportWidget({
  isAuthenticated,
  isAdmin,
  open,
  setOpen,
  tickets = [],
  selectedTicketId,
  setSelectedTicketId,
  messagesByTicket = {},
  drafts = {},
  form,
  setForm,
  loading,
  onCreate,
  onDraftChange,
  onSend,
  onStatusChange,
  navigate,
}) {
  const selected = tickets.find((ticket) => String(ticket.id) === String(selectedTicketId)) || tickets[0] || null;
  const messages = selected ? (messagesByTicket[selected.id] || []) : [];

  return (
    <div className={`support-widget ${open ? "is-open" : ""}`}>
      {open && (
        <section className="support-panel glass-panel">
          <div className="panel-title">
            <MessageCircle size={20} />
            <h3>Техподдержка</h3>
          </div>
          {!isAuthenticated ? (
            <div className="support-login">
              <p>Войдите, чтобы создать обращение или ответить в тикете.</p>
              <button className="primary-button" type="button" onClick={() => navigate("/login")}>Войти</button>
            </div>
          ) : (
            <>
              <div className="support-ticket-list">
                {tickets.length ? tickets.map((ticket) => (
                  <button
                    type="button"
                    className={String(selected?.id) === String(ticket.id) ? "active" : ""}
                    key={ticket.id}
                    onClick={() => setSelectedTicketId(String(ticket.id))}
                  >
                    <span>{ticket.subject}</span>
                    <small>{statusLabel(ticket.status)} · {formatDate(ticket.updated_at)}</small>
                  </button>
                )) : (
                  <p className="empty-state">Пока нет обращений.</p>
                )}
              </div>

              {selected && (
                <div className="support-chat-box">
                  <div className="support-ticket-header">
                    <strong>{selected.subject}</strong>
                    <StatusPill value={selected.status} />
                  </div>
                  {isAdmin && (
                    <select value={selected.status} onChange={(event) => onStatusChange(selected.id, event.target.value)}>
                      <option value="open">open</option>
                      <option value="in_progress">in_progress</option>
                      <option value="resolved">resolved</option>
                      <option value="closed">closed</option>
                    </select>
                  )}
                  <div className="chat-thread compact-thread">
                    {messages.length ? messages.map((message) => (
                      <div className={`chat-message ${message.is_system ? "is-system" : ""}`} key={message.id}>
                        <strong>{message.is_system ? "Система" : (message.sender?.username || "Пользователь")}</strong>
                        <p>{message.message}</p>
                        <small>{formatDate(message.created_at)}</small>
                      </div>
                    )) : <p className="empty-state">Сообщений пока нет.</p>}
                  </div>
                  <form className="chat-form" onSubmit={(event) => { event.preventDefault(); onSend(selected.id); }}>
                    <input
                      value={drafts[selected.id] || ""}
                      onChange={(event) => onDraftChange(selected.id, event.target.value)}
                      placeholder="Ответить в тикет"
                    />
                    <button className="primary-button" type="submit" disabled={loading || !(drafts[selected.id] || "").trim()}>
                      <Send size={16} />
                    </button>
                  </form>
                </div>
              )}

              {!isAdmin && (
                <form className="support-new-ticket" onSubmit={onCreate}>
                  <strong>Новое обращение</strong>
                  <input value={form.subject} onChange={(event) => setForm({ ...form, subject: event.target.value })} placeholder="Тема проблемы" />
                  <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>
                    <option value="service">Сервис</option>
                    <option value="weather">Погода</option>
                    <option value="station">Станция</option>
                    <option value="account">Аккаунт</option>
                  </select>
                  <textarea value={form.message} onChange={(event) => setForm({ ...form, message: event.target.value })} placeholder="Опишите проблему" />
                  <button className="primary-button" type="submit" disabled={loading}>
                    Создать тикет
                  </button>
                </form>
              )}
            </>
          )}
        </section>
      )}
      <button className="support-fab" type="button" onClick={() => setOpen(!open)} aria-label="Техподдержка">
        <MessageCircle size={22} />
      </button>
    </div>
  );
}

function FirmwareCodeBlock({ code }) {
  if (!code) {
    return <small>Код прошивки появится после генерации.</small>;
  }
  return (
    <div className="firmware-code">
      <div className="firmware-code-header">
        <span>Сгенерированный код</span>
        <button className="icon-text-button" type="button" onClick={() => navigator.clipboard?.writeText(code)}>
          <Copy size={15} />
          Скопировать
        </button>
      </div>
      <pre>{code}</pre>
    </div>
  );
}

function DwdApplicationForm({ form, loading, setForm, onSubmit }) {
  return (
    <form className="dwd-form" onSubmit={onSubmit}>
      <label>
        <span>Город устройства</span>
        <input
          value={form.city}
          onChange={(event) => setForm({ ...form, city: event.target.value })}
          placeholder="Berlin"
          required
        />
      </label>
      <label>
        <span>Email для связи</span>
        <input
          type="email"
          value={form.email}
          onChange={(event) => setForm({ ...form, email: event.target.value })}
          placeholder="device-contact@example.com"
          required
        />
      </label>
      <label>
        <span>Комментарий к заявке</span>
        <textarea
          value={form.comment}
          onChange={(event) => setForm({ ...form, comment: event.target.value })}
          placeholder="Хочу подключить своё DWD-устройство."
          required
        />
      </label>
      <button className="primary-button" type="submit" disabled={loading}>
        {loading ? <RefreshCw className="spin" size={18} /> : <Send size={18} />}
        Отправить заявку
      </button>
    </form>
  );
}

function DwdApplicationsList({ applications }) {
  return (
    <div className="dwd-grid">
      <article className="dwd-card">
        <div className="panel-title">
          <ShieldCheck size={20} />
          <h3>Ваши заявки DWD</h3>
        </div>
        {applications.length ? (
          <div className="dwd-list">
            {applications.map((application) => (
              <div className="dwd-list-item" key={application.id}>
                <div>
                  <strong>{application.city}</strong>
                  <small>{application.email}</small>
                  <small>{application.comment}</small>
                </div>
                <StatusPill value={application.status} />
              </div>
            ))}
          </div>
        ) : (
          <p className="empty-state">Заявок DWD пока нет.</p>
        )}
      </article>
    </div>
  );
}

function ProviderCabinet({ dashboard, firmwareForm, loading, onFirmwareFieldChange, onFirmwareSubmit }) {
  if (!dashboard) return null;
  const devices = dashboard.devices || [];
  const provisioning = dashboard.provisioning || [];
  const selectedDeviceId = firmwareForm.device_id || (devices[0]?.id ? String(devices[0].id) : "");

  return (
    <div className="dwd-grid two-columns">
      <article className="dwd-card">
        <div className="panel-title">
          <Cpu size={20} />
          <h3>Ваши устройства</h3>
        </div>
        {devices.length ? (
          <div className="dwd-list">
            {devices.map((device) => (
              <div className="dwd-list-item" key={device.id}>
                <div>
                  <strong>{device.device_code || device.station_id}</strong>
                  <small>{device.city} / {device.firmware_type || "прошивка ещё не выбрана"}</small>
                  <small>Последний heartbeat: {formatDate(device.last_seen_at)}</small>
                </div>
                <StatusPill value={device.online_status || device.status} />
              </div>
            ))}
          </div>
        ) : (
          <p className="empty-state">Карточка устройства появится после одобрения заявки.</p>
        )}
      </article>

      <article className="dwd-card">
        <div className="panel-title">
          <Settings size={20} />
          <h3>Собрать прошивку</h3>
        </div>
        {devices.length ? (
          <form className="dwd-form compact-form" onSubmit={onFirmwareSubmit}>
            <label>
              <span>Устройство</span>
              <select
                value={selectedDeviceId}
                onChange={(event) => onFirmwareFieldChange("device_id", event.target.value)}
                required
              >
                {devices.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.device_code || device.station_id} / {device.city}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Режим</span>
              <select value={firmwareForm.firmware_type} onChange={(event) => onFirmwareFieldChange("firmware_type", event.target.value)}>
                <option value="esp01_wifi">MQTT Wi-Fi</option>
              </select>
            </label>
            <label>
              <span>Версия</span>
              <input
                value={firmwareForm.firmware_version}
                onChange={(event) => onFirmwareFieldChange("firmware_version", event.target.value)}
                placeholder="1.0.0"
              />
            </label>
            <label>
              <span>Wi-Fi сеть</span>
              <input
                value={firmwareForm.wifi_ssid}
                onChange={(event) => onFirmwareFieldChange("wifi_ssid", event.target.value)}
                placeholder="Например, HomeWiFi"
                required
              />
            </label>
            <label>
              <span>Wi-Fi пароль</span>
              <input
                type="password"
                value={firmwareForm.wifi_password}
                onChange={(event) => onFirmwareFieldChange("wifi_password", event.target.value)}
                placeholder="Пароль от вашей сети"
                autoComplete="new-password"
              />
            </label>
            <p className="empty-state wide-field">
              Station ID, MQTT topic, адрес сервера и ключи доступа сайт подставит сам. Вам не нужно искать или вводить системные параметры.
            </p>
            <button className="primary-button" type="submit" disabled={loading || !selectedDeviceId}>
              {loading ? <RefreshCw className="spin" size={18} /> : <Terminal size={18} />}
              Сгенерировать код
            </button>
          </form>
        ) : (
          <p className="empty-state">Генерация откроется после одобрения заявки и создания устройства.</p>
        )}
      </article>

      <article className="dwd-card">
        <div className="panel-title">
          <FileText size={20} />
          <h3>Ваш Arduino-код</h3>
        </div>
        {provisioning.length ? (
          <div className="dwd-list">
            {provisioning.map((record) => (
              <div className="dwd-list-item" key={record.id}>
                <div>
                  <strong>{record.firmware_type} {record.firmware_version}</strong>
                  <small>Устройство: {record.device?.device_code || record.device?.station_id || "не указано"}</small>
                  <small>Сгенерировано: {formatDate(record.code_generated_at || record.updated_at)}</small>
                  <small>{record.wifi_configured ? "Wi-Fi уже вписан в код" : "Wi-Fi ещё не вписан"}</small>
                  <FirmwareCodeBlock code={record.firmware_code} />
                </div>
                <StatusPill value={record.delivery_status} />
              </div>
            ))}
          </div>
        ) : (
          <p className="empty-state">Код появится здесь после генерации.</p>
        )}
      </article>
    </div>
  );
}

function DwdAdminPanel({
  applications,
  devices,
  provisioningRecords,
  provisioningForm,
  loading,
  onApprove,
  onReject,
  onPrepareProvisioning,
  onProvisioningFieldChange,
  onProvisioningSubmit,
  onProvisioningSent,
}) {
  const selectedApplication = applications.find((item) => String(item.id) === String(provisioningForm.application_id));

  return (
    <div className="dwd-admin">
      <div className="section-heading compact-heading">
        <div>
          <span className="eyebrow">Админка</span>
          <h2>Рабочая область DWD provisioning</h2>
        </div>
        <StatusPill value="admin" />
      </div>

      <div className="dwd-grid two-columns">
        <article className="dwd-card">
          <div className="panel-title">
            <FileText size={20} />
            <h3>Заявки</h3>
          </div>
          {applications.length ? (
            <div className="dwd-list">
              {applications.map((application) => (
                <div className="dwd-list-item application-item" key={application.id}>
                  <div>
                    <strong>{application.city}</strong>
                    <small>{formatUser(application.user)}</small>
                    <small>{application.comment}</small>
                  </div>
                  <div className="row-actions">
                    <StatusPill value={application.status} />
                    {application.status === "pending" ? (
                      <>
                        <button className="icon-text-button" type="button" disabled={loading} onClick={() => onApprove(application.id)}>
                          <CheckCircle2 size={16} />
                          Одобрить
                        </button>
                        <button className="icon-text-button" type="button" disabled={loading} onClick={() => onReject(application.id)}>
                          Отклонить
                        </button>
                      </>
                    ) : (
                      <button className="icon-text-button" type="button" disabled={loading} onClick={() => onPrepareProvisioning(application)}>
                        <Radio size={16} />
                        Настроить
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-state">Заявок provider пока нет.</p>
          )}
        </article>

        <article className="dwd-card" id="dwd-provisioning-form">
          <div className="panel-title">
            <Radio size={20} />
            <h3>Назначение прошивки</h3>
          </div>
          {selectedApplication && (
            <p className="empty-state">
              Выбрано: {selectedApplication.city} / {formatUser(selectedApplication.user)}
            </p>
          )}
          <form className="dwd-form compact-form" onSubmit={onProvisioningSubmit}>
            <label>
              <span>Заявка</span>
              <select
                value={provisioningForm.application_id}
                onChange={(event) => {
                  const application = applications.find((item) => String(item.id) === event.target.value);
                  if (application) onPrepareProvisioning(application);
                  else onProvisioningFieldChange("application_id", event.target.value);
                }}
                required
              >
                <option value="">Выберите одобренную заявку</option>
                {applications.filter((item) => item.status === "approved").map((application) => (
                  <option key={application.id} value={application.id}>
                    #{application.id} {application.city} / {application.user?.username}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Тип прошивки</span>
              <select
                value={provisioningForm.firmware_type}
                onChange={(event) => onProvisioningFieldChange("firmware_type", event.target.value)}
              >
                <option value="serial_bridge">serial_bridge</option>
                <option value="esp01_wifi">esp01_wifi</option>
                <option value="ethernet_shield">ethernet_shield</option>
              </select>
            </label>
            <label>
              <span>Версия</span>
              <input
                value={provisioningForm.firmware_version}
                onChange={(event) => onProvisioningFieldChange("firmware_version", event.target.value)}
                placeholder="1.0.0"
              />
            </label>
            <label>
              <span>Канал отправки</span>
              <select
                value={provisioningForm.delivery_channel}
                onChange={(event) => onProvisioningFieldChange("delivery_channel", event.target.value)}
              >
                <option value="email">email</option>
                <option value="manual">вручную</option>
              </select>
            </label>
            <label className="wide-field">
              <span>Текст инструкции</span>
              <textarea
                value={provisioningForm.instruction_text}
                onChange={(event) => onProvisioningFieldChange("instruction_text", event.target.value)}
                required
              />
            </label>
            <label className="wide-field">
              <span>Заметки</span>
              <textarea
                value={provisioningForm.notes}
                onChange={(event) => onProvisioningFieldChange("notes", event.target.value)}
                placeholder="Внутренняя заметка"
              />
            </label>
            <button className="primary-button" type="submit" disabled={loading || !provisioningForm.application_id}>
              {loading ? <RefreshCw className="spin" size={18} /> : <FileText size={18} />}
              Сохранить инструкцию
            </button>
          </form>
        </article>
      </div>

      <div className="dwd-grid two-columns">
        <article className="dwd-card">
          <div className="panel-title">
            <Cpu size={20} />
            <h3>Устройства</h3>
          </div>
          {devices.length ? (
            <div className="dwd-list">
              {devices.map((device) => (
                <div className="dwd-list-item" key={device.id}>
                  <div>
                    <strong>{device.station_id}</strong>
                    <small>{device.city} / {formatUser(device.owner)}</small>
                    <small>{device.firmware_type || "прошивка не выбрана"} {device.firmware_version || ""}</small>
                  </div>
                  <StatusPill value={device.provisioning_status || device.status} />
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-state">Карточки устройств появятся после одобрения заявок.</p>
          )}
        </article>

        <article className="dwd-card">
          <div className="panel-title">
            <Send size={20} />
            <h3>Инструкции</h3>
          </div>
          {provisioningRecords.length ? (
            <div className="dwd-list">
              {provisioningRecords.map((record) => (
                <div className="dwd-list-item" key={record.id}>
                  <div>
                    <strong>{record.firmware_type} {record.firmware_version}</strong>
                    <small>{formatUser(record.user)}</small>
                    <small>{record.sent_at ? `Отправлено ${formatDate(record.sent_at)}` : "Пока не отправлено"}</small>
                  </div>
                  <div className="row-actions">
                    <StatusPill value={record.delivery_status} />
                    {record.delivery_status !== "sent" && (
                      <button className="icon-text-button" type="button" disabled={loading} onClick={() => onProvisioningSent(record.id)}>
                        <Send size={16} />
                        Отправлено
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-state">Инструкций по прошивке пока нет.</p>
          )}
        </article>
      </div>
    </div>
  );
}

function AuthPanel({
  authMode,
  authForm,
  authStatus,
  login2FAChallenge,
  login2FAForm,
  loading,
  setAuthForm,
  setAuthMode,
  setLogin2FAChallenge,
  setLogin2FAForm,
  handleAuth,
  handleLogin2FASubmit,
  navigate,
}) {
  return (
    <aside className="auth-panel glass-panel reveal is-visible" id={authMode === "register" ? "register" : "login"}>
      <div className="panel-title">
        {authMode === "login" ? <LogIn size={20} /> : <UserPlus size={20} />}
        <h2>{authMode === "login" ? "Вход" : "Регистрация"}</h2>
      </div>
      <form className="auth-form" onSubmit={handleAuth}>
        <input value={authForm.username} onChange={(event) => setAuthForm({ ...authForm, username: event.target.value })} placeholder={authMode === "login" ? "Логин или email" : "Никнейм"} autoComplete="username" required />
        {authMode === "register" && (
          <input value={authForm.email} onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })} placeholder="Email" type="email" autoComplete="email" required />
        )}
        <input value={authForm.password} onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })} placeholder="Пароль" type="password" minLength={authMode === "register" ? 8 : undefined} autoComplete={authMode === "login" ? "current-password" : "new-password"} required />
        <button className="primary-button" type="submit" disabled={loading}>
          {loading ? <RefreshCw className="spin" size={18} /> : authMode === "login" ? <LogIn size={18} /> : <UserPlus size={18} />}
          {authMode === "login" ? "Войти" : "Создать"}
        </button>
      </form>
      {login2FAChallenge && authMode === "login" && (
        <form className="auth-form two-factor-form" onSubmit={handleLogin2FASubmit}>
          <div className="telegram-hint">
            <ShieldCheck size={18} />
            <span>
              Введите код из Telegram. Бот:{" "}
              <a href={login2FAChallenge.telegram_bot_url} target="_blank" rel="noreferrer">
                {login2FAChallenge.telegram_bot_username || "@darkweather_2fa_bot"}
              </a>
            </span>
          </div>
          <input
            value={login2FAForm.code}
            onChange={(event) => setLogin2FAForm({ ...login2FAForm, code: event.target.value })}
            placeholder="Код из Telegram"
            inputMode="numeric"
            required
          />
          <button className="primary-button" type="submit" disabled={loading}>
            {loading ? <RefreshCw className="spin" size={18} /> : <ShieldCheck size={18} />}
            Подтвердить вход
          </button>
        </form>
      )}
      <button className="text-button" onClick={() => {
        const nextMode = authMode === "login" ? "register" : "login";
        setAuthMode(nextMode);
        setLogin2FAChallenge(null);
        setLogin2FAForm(DEFAULT_LOGIN_2FA_FORM);
        navigate(nextMode === "login" ? "/login" : "/register");
      }}>
        {authMode === "login" ? "Нужен аккаунт" : "Уже есть аккаунт"}
      </button>
      {authStatus && <p className="status-message">{authStatus}</p>}
    </aside>
  );
}

function AccessGate({ text, navigate }) {
  return (
    <div className="access-gate">
      <div className="panel-title">
        <Lock size={20} />
        <h2>Доступ закрыт</h2>
      </div>
      <p>{text}</p>
      <div className="access-actions">
        <button className="primary-button" onClick={() => navigate("/login")}><LogIn size={18} />Войти</button>
        <button className="icon-text-button" onClick={() => navigate("/register")}><UserPlus size={18} />Регистрация</button>
      </div>
    </div>
  );
}

function ExtendedForecastSection({ isAuthenticated, open, data, loading, onToggle, navigate }) {
  const [selectedDate, setSelectedDate] = useState("");
  const [hourIndex, setHourIndex] = useState(0);
  const [hourTransition, setHourTransition] = useState("next");
  const activeHourRef = useRef(null);
  const daily = data?.daily || [];
  const hourly = data?.hourly || [];
  const activeDate = selectedDate || daily[0]?.date || "";
  const selectedDay = daily.find((day) => day.date === activeDate) || daily[0];
  const selectedHours = hourly.filter((hour) => getHourlyDate(hour) === activeDate);
  const activeHour = selectedHours[Math.min(hourIndex, Math.max(selectedHours.length - 1, 0))];

  useEffect(() => {
    if (!daily.length) {
      setSelectedDate("");
      setHourIndex(0);
      return;
    }
    if (!daily.some((day) => day.date === selectedDate)) {
      setSelectedDate(daily[0].date);
      setHourIndex(0);
    }
  }, [daily, selectedDate]);

  useEffect(() => {
    setHourIndex(0);
  }, [selectedDate]);

  useEffect(() => {
    if (selectedHours.length && hourIndex > selectedHours.length - 1) {
      setHourIndex(selectedHours.length - 1);
    }
  }, [hourIndex, selectedHours.length]);

  useEffect(() => {
    activeHourRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [hourIndex, selectedDate]);

  function selectHour(nextIndex) {
    if (nextIndex === hourIndex) return;
    setHourTransition(nextIndex > hourIndex ? "next" : "prev");
    setHourIndex(nextIndex);
  }

  function moveHour(delta) {
    const nextIndex = Math.min(Math.max(hourIndex + delta, 0), Math.max(selectedHours.length - 1, 0));
    selectHour(nextIndex);
  }

  return (
    <section className="extended-section glass-panel reveal is-visible">
      <div className="section-heading">
        <div>
          <span className="eyebrow">На ближайшие дни</span>
          <h2>Подробный прогноз</h2>
        </div>
      </div>

      {!isAuthenticated ? (
        <AccessGate navigate={navigate} text="Подробный прогноз доступен после входа в аккаунт." />
      ) : (
        <>
          <button className="icon-text-button extended-toggle" type="button" onClick={onToggle} disabled={loading}>
            {loading ? <RefreshCw className="spin" size={18} /> : <CloudSun size={18} />}
            {open ? "Скрыть подробный прогноз" : "Показать больше"}
          </button>

          {open && (
            <div className="extended-content">
              {loading && !data ? (
                <p className="empty-state">Загружаем расширенный прогноз...</p>
              ) : daily.length ? (
                <>
                  <div className="forecast-days" role="tablist" aria-label="Дни прогноза">
                    {daily.map((day) => (
                      <button
                        className={day.date === activeDate ? "active" : ""}
                        key={day.date}
                        type="button"
                        role="tab"
                        aria-selected={day.date === activeDate}
                        onClick={() => setSelectedDate(day.date)}
                      >
                        <strong>{formatForecastDate(day.date)}</strong>
                        <span>{formatNumber(day.temp_min)}...{formatNumber(day.temp_max)} C</span>
                      </button>
                    ))}
                  </div>

                  <article className="forecast-detail">
                    <div className="forecast-summary">
                      <div>
                        <span className="eyebrow">{formatForecastDate(selectedDay?.date)}</span>
                        <h3>{translateWeatherCondition(selectedDay?.conditions) || "Подробный прогноз"}</h3>
                      </div>
                      <span className="cache-pill">{selectedHours.length ? `${selectedHours.length} часов` : "Нет почасовых данных"}</span>
                    </div>

                    <div className="forecast-values forecast-values-grid">
                      <Metric icon={<Thermometer size={18} />} label="Температура за день" value={`${formatNumber(selectedDay?.temp_min)}...${formatNumber(selectedDay?.temp_max)} C`} />
                      <Metric icon={<Droplets size={18} />} label="Влажность" value={`${formatNumber(selectedDay?.humidity, 0)}%`} />
                      <Metric icon={<Wind size={18} />} label="Ветер" value={`${formatNumber(selectedDay?.wind_speed)} m/s`} />
                      <Metric icon={<Waves size={18} />} label="Вероятность осадков" value={`${formatNumber(selectedDay?.precip_probability, 0)}%`} />
                    </div>

                    {selectedHours.length ? (
                      <div className="hourly-panel">
                        <div className={`hourly-current hourly-current-${hourTransition}`} key={`${activeDate}-${hourIndex}-${hourTransition}-summary`}>
                          <strong>{activeHour?.time || formatHourLabel(activeHour)}</strong>
                          <span>{translateWeatherCondition(activeHour?.conditions) || "Без описания"}</span>
                        </div>

                        <div className="hourly-carousel" aria-label="Почасовой прогноз">
                          <button
                            aria-label="Предыдущий час"
                            className="icon-button hourly-arrow"
                            disabled={hourIndex <= 0}
                            type="button"
                            onClick={() => moveHour(-1)}
                          >
                            <ChevronLeft size={20} />
                          </button>

                          <div className="hourly-track" role="listbox" aria-label="Часы выбранного дня">
                            {selectedHours.map((hour, index) => (
                              <button
                                aria-selected={index === hourIndex}
                                className={`hour-chip ${index === hourIndex ? "active" : ""}`}
                                key={`${hour.datetime}-${index}`}
                                ref={index === hourIndex ? activeHourRef : null}
                                role="option"
                                type="button"
                                onClick={() => selectHour(index)}
                              >
                                <strong>{hour.time || formatHourLabel(hour)}</strong>
                                <span>{formatNumber(hour.temp)} C</span>
                              </button>
                            ))}
                          </div>

                          <button
                            aria-label="Следующий час"
                            className="icon-button hourly-arrow"
                            disabled={hourIndex >= selectedHours.length - 1}
                            type="button"
                            onClick={() => moveHour(1)}
                          >
                            <ChevronRight size={20} />
                          </button>
                        </div>

                        <div className={`hourly-metrics hourly-metrics-${hourTransition}`} key={`${activeDate}-${hourIndex}-${hourTransition}-metrics`}>
                          <Metric icon={<Thermometer size={18} />} label="Температура" value={`${formatNumber(activeHour?.temp)} C`} />
                          <Metric icon={<Droplets size={18} />} label="Влажность" value={`${formatNumber(activeHour?.humidity, 0)}%`} />
                          <Metric icon={<Wind size={18} />} label="Ветер" value={`${formatNumber(activeHour?.wind_speed)} m/s`} />
                          <Metric icon={<Waves size={18} />} label="Осадки" value={`${formatNumber(activeHour?.precip_probability, 0)}%`} />
                        </div>
                      </div>
                    ) : (
                      <p className="empty-state">Для выбранного дня почасовых данных нет.</p>
                    )}
                  </article>
                </>
              ) : (
                <p className="empty-state">Подробный прогноз пока пуст.</p>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function getHourlyDate(hour) {
  if (hour?.date) return hour.date;
  if (hour?.datetime) return String(hour.datetime).slice(0, 10);
  return "";
}

function formatHourLabel(hour) {
  const value = hour?.time || hour?.datetime;
  if (!value) return "—";
  const parts = String(value).split("T");
  return (parts[1] || parts[0]).slice(0, 5);
}

function formatForecastDate(value) {
  if (!value) return "Дата не указана";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    weekday: "short",
  }).format(new Date(`${value}T12:00:00`));
}

const WEATHER_CONDITION_LABELS = {
  clear: "Ясно",
  sunny: "Солнечно",
  cloudy: "Облачно",
  overcast: "Пасмурно",
  "partially cloudy": "Переменная облачность",
  "partly cloudy": "Переменная облачность",
  "partial cloudly": "Переменная облачность",
  "partially cloudly": "Переменная облачность",
  rain: "Дождь",
  "light rain": "Небольшой дождь",
  "heavy rain": "Сильный дождь",
  showers: "Ливневый дождь",
  drizzle: "Морось",
  snow: "Снег",
  "light snow": "Небольшой снег",
  "heavy snow": "Сильный снег",
  sleet: "Мокрый снег",
  "freezing rain": "Ледяной дождь",
  "freezing drizzle": "Ледяная морось",
  ice: "Гололёд",
  hail: "Град",
  thunderstorm: "Гроза",
  thunderstorms: "Грозы",
  fog: "Туман",
  mist: "Дымка",
  haze: "Мгла",
  wind: "Ветрено",
  windy: "Ветрено",
  dust: "Пыль",
  smoke: "Дымка",
};

function translateWeatherCondition(value) {
  if (!value) return "";
  const parts = String(value)
    .split(/[,;]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return "";

  return parts.map((part) => {
    const key = part.toLowerCase().replace(/\s+/g, " ");
    if (WEATHER_CONDITION_LABELS[key]) return WEATHER_CONDITION_LABELS[key];
    return part
      .replace(/\bPartially cloudy\b/gi, "Переменная облачность")
      .replace(/\bPartly cloudy\b/gi, "Переменная облачность")
      .replace(/\bPartially cloudly\b/gi, "Переменная облачность")
      .replace(/\bOvercast\b/gi, "Пасмурно")
      .replace(/\bCloudy\b/gi, "Облачно")
      .replace(/\bClear\b/gi, "Ясно")
      .replace(/\bRain\b/gi, "Дождь")
      .replace(/\bSnow\b/gi, "Снег")
      .replace(/\bFog\b/gi, "Туман")
      .replace(/\bThunderstorm\b/gi, "Гроза");
  }).join(", ");
}

function WeatherCard({ weather }) {
  return (
    <article className="weather-card glass-panel reveal">
      <div className="panel-title">
        <Thermometer size={20} />
        <h2>Погода сейчас</h2>
      </div>
      <div className="temperature-display">{formatNumber(weather?.temperature_c)}<span>°C</span></div>
      <div className="metric-list">
        <Metric icon={<Waves size={18} />} label="Давление" value={`${formatNumber(weather?.pressure_hpa, 0)} hPa`} />
        <Metric icon={<Wind size={18} />} label="Ветер" value={`${formatNumber(weather?.wind_speed_ms)} m/s`} />
        <Metric icon={<Droplets size={18} />} label="Осадки" value={`${formatNumber(weather?.precipitation_mm)} mm`} />
      </div>
      <footer className="card-footer">
        <span>{weather?.observed_at ? `Обновлено ${formatDate(weather.observed_at)}` : "Введите город, чтобы узнать погоду"}</span>
      </footer>
    </article>
  );
}

function OutfitCard({ outfit }) {
  const recommendation = cleanRecommendationText(outfit?.recommendation);

  return (
    <article className="outfit-card glass-panel reveal">
      <div className="panel-title">
        <Sparkles size={20} />
        <h2>Совет по одежде</h2>
      </div>
      <p>{recommendation || "Рекомендация появится после первого погодного запроса."}</p>
    </article>
  );
}

function StationLatest({ reading }) {
  if (!reading || reading.available === false) {
    const city = reading?.city ? ` ${reading.city}` : "";
    const message = reading?.status === "stale"
      ? "Данные станции устарели. Дождитесь нового измерения от Dark Weather Device."
      : `В данном городе${city} нет ни одного Dark Weather Device.`;
    return (
      <div className="station-empty">
        <Cpu size={22} />
        <div>
          <strong>Нет последних данных</strong>
          <p>{message}</p>
        </div>
      </div>
    );
  }

  const station = reading.station || null;
  const payload = reading.reading || reading;
  const temperature = payload.temperature_c ?? payload.temperature;
  const items = [
    ["Температура", `${formatNumber(temperature)} °C`, <Thermometer size={18} />],
    ["Влажность", `${formatNumber(payload?.humidity, 0)}%`, <Droplets size={18} />],
  ];
  if (payload?.pressure_hpa !== null && payload?.pressure_hpa !== undefined) {
    items.push(["Давление", `${formatNumber(payload.pressure_hpa, 0)} hPa`, <Waves size={18} />]);
  }
  if (payload?.wind_speed_ms !== null && payload?.wind_speed_ms !== undefined) {
    items.push(["Ветер", `${formatNumber(payload.wind_speed_ms)} m/s`, <Wind size={18} />]);
  }

  return (
    <div className="station-latest">
      {items.map(([label, value, icon]) => (
        <Metric key={label} icon={icon} label={label} value={value} />
      ))}
      <Metric icon={<Cpu size={18} />} label="Станция" value={station ? `${station.name || station.station_id} · ${station.city}` : "Локальное устройство"} />
      <Metric icon={<RefreshCw size={18} />} label="Обновлено" value={formatDate(payload?.created_at || payload?.observed_at)} />
    </div>
  );
}

function Metric({ icon, label, value }) {
  return (
    <div className="metric">
      <span className="metric-icon">{icon}</span>
      <span>
        <small>{label}</small>
        <strong>{value}</strong>
      </span>
    </div>
  );
}

function LineChart({ title, data, dataKey, unit, color }) {
  const values = data
    .map((item) => ({
      value: Number(item[dataKey]),
      observed_at: item.observed_at || item.hour_bucket,
      label: formatDate(item.observed_at || item.hour_bucket),
    }))
    .filter((item) => Number.isFinite(item.value));

  const width = 420;
  const height = 190;
  const padding = { top: 18, right: 16, bottom: 30, left: 40 };
  const min = values.length ? Math.min(...values.map((item) => item.value)) : 0;
  const max = values.length ? Math.max(...values.map((item) => item.value)) : 1;
  const spread = max - min || 1;
  const yMin = min - spread * 0.12;
  const yMax = max + spread * 0.12;
  const ySpread = yMax - yMin || 1;
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const ticks = [0, 0.5, 1].map((ratio) => yMax - ySpread * ratio);
  const points = values.map((item, index) => {
    const x = padding.left + (index / Math.max(values.length - 1, 1)) * chartWidth;
    const y = padding.top + ((yMax - item.value) / ySpread) * chartHeight;
    return { ...item, x, y };
  });
  const latest = values.at(-1);
  const pointString = points.map((point) => `${point.x},${point.y}`).join(" ");
  const areaString = `${padding.left},${height - padding.bottom} ${pointString} ${width - padding.right},${height - padding.bottom}`;

  return (
    <article className="chart-card">
      <header>
        <span>{title}</span>
        <strong>{latest ? `${formatNumber(latest.value)} ${unit}` : "—"}</strong>
      </header>
      {values.length > 1 ? (
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
          <defs>
            <linearGradient id={`fill-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.32" />
              <stop offset="100%" stopColor={color} stopOpacity="0.02" />
            </linearGradient>
          </defs>
          {ticks.map((tick) => {
            const y = padding.top + ((yMax - tick) / ySpread) * chartHeight;
            return (
              <g key={tick}>
                <line className="chart-grid-line" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
                <text className="chart-axis-label" x={padding.left - 8} y={y + 4} textAnchor="end">{formatNumber(tick)}</text>
              </g>
            );
          })}
          <polyline className="chart-area" points={areaString} fill={`url(#fill-${dataKey})`} />
          <polyline className="chart-line" points={pointString} fill="none" stroke={color} />
          {points.map((point, index) => index % Math.ceil(points.length / 6) === 0 || index === points.length - 1 ? (
            <circle key={`${point.x}-${point.y}`} className="chart-dot" cx={point.x} cy={point.y} r="4" fill={color}>
              <title>{`${point.label}: ${formatNumber(point.value)} ${unit}`}</title>
            </circle>
          ) : null)}
          <line className="chart-base-line" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
        </svg>
      ) : (
        <div className="chart-empty">Недостаточно точек</div>
      )}
      <footer>
        <span>{values[0] ? formatDate(values[0].observed_at) : "—"}</span>
        <span>{latest ? formatDate(latest.observed_at) : "—"}</span>
      </footer>
    </article>
  );
}

export default App;
