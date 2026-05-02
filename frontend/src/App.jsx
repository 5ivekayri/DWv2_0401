import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  CloudSun,
  Cpu,
  Droplets,
  Lock,
  LogIn,
  LogOut,
  MapPin,
  Moon,
  RefreshCw,
  Search,
  Sparkles,
  Sun,
  Thermometer,
  UserPlus,
  Waves,
  Wind,
} from "lucide-react";
import {
  apiRequest,
  clearTokens,
  geocodeCity,
  login,
  readTokens,
  saveTokens,
  signup,
} from "./api";

const DEFAULT_COORDS = {
  city: "Moscow",
  lat: "55.7512",
  lon: "37.6184",
};

const THEME_KEY = "dwv2_theme";

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

function getErrorMessage(error) {
  if (!error) return "";
  if (error.status === 401) return "Сессия истекла или нужен вход.";
  if (error.status === 503) return "AI сервис пока не настроен на backend.";
  if (error.status === 502) return "Внешний погодный или AI сервис не ответил.";
  return error.message || "Что-то пошло не так.";
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
  const [weatherHistory, setWeatherHistory] = useState([]);
  const [outfit, setOutfit] = useState(null);
  const [stationId, setStationId] = useState("arduino-1");
  const [stationLatest, setStationLatest] = useState(null);
  const [stationHistory, setStationHistory] = useState([]);
  const [loading, setLoading] = useState({ weather: false, station: false, auth: false });
  const [notice, setNotice] = useState("");

  const isAuthenticated = Boolean(tokens?.access);

  useEffect(() => {
    loadWeather();
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      loadStation(tokens);
    } else {
      setStationLatest(null);
      setStationHistory([]);
    }
  }, [isAuthenticated]);

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

    revealItems.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, []);

  async function runTask(key, task) {
    setLoading((current) => ({ ...current, [key]: true }));
    setNotice("");
    try {
      await task();
    } catch (error) {
      setNotice(getErrorMessage(error));
    } finally {
      setLoading((current) => ({ ...current, [key]: false }));
    }
  }

  async function handleAuth(event) {
    event.preventDefault();
    setAuthStatus("");

    await runTask("auth", async () => {
      if (authMode === "register") {
        await signup(authForm.username, authForm.email, authForm.password);
        setAuthMode("login");
        setAuthStatus("Аккаунт создан. Теперь можно войти.");
        navigate("/login");
        return;
      }

      const nextTokens = await login(authForm.username, authForm.password);
      saveTokens(nextTokens);
      setTokens(nextTokens);
      setAuthStatus("Вход выполнен.");
      await loadWeather(nextTokens);
      await loadStation(nextTokens);
      navigate("/weather");
    });
  }

  function handleLogout() {
    clearTokens();
    setTokens(null);
    setWeatherHistory([]);
    setStationLatest(null);
    setStationHistory([]);
    setAuthStatus("Вы вышли из аккаунта.");
  }

  function navigate(path) {
    window.history.pushState({}, "", path);
    setPathname(path);
    setAuthMode(path.includes("register") ? "register" : "login");
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
    const place = await geocodeCity(coords.city.trim());
    const nextCoords = {
      city: place.city,
      lat: String(place.latitude),
      lon: String(place.longitude),
    };
    setCoords(nextCoords);
    return nextCoords;
  }

  async function loadWeather(nextTokens = tokens, nextCoords = coords) {
    await runTask("weather", async () => {
      const target = searchMode === "city" ? await resolveCity() : nextCoords;
      const params = new URLSearchParams({ lat: target.lat, lon: target.lon });
      const current = await apiRequest(`/weather?${params}`);
      setWeather(current);

      const condition = current.precipitation_mm > 0 ? "rain" : "cloudy";
      apiRequest("/ai/outfit-recommendation", {
        method: "POST",
        body: JSON.stringify({
          city: target.city || "Selected location",
          temperature_c: current.temperature_c,
          humidity: stationLatest?.humidity ?? 70,
          wind_speed_ms: current.wind_speed_ms,
          precipitation_mm: current.precipitation_mm,
          condition,
        }),
      })
        .then(setOutfit)
        .catch((error) => setOutfit({ recommendation: getErrorMessage(error), source: "unavailable" }));

      await loadWeatherHistory(params, nextTokens);
    });
  }

  async function loadWeatherHistory(params, nextTokens = tokens) {
    if (!nextTokens?.access) {
      setWeatherHistory([]);
      return;
    }

    try {
      const history = await apiRequest(`/weather/history?${params}&limit=24`, {}, nextTokens);
      setWeatherHistory(history.results || []);
    } catch (error) {
      setWeatherHistory([]);
      if (error.status === 401) {
        clearTokens();
        setTokens(null);
      }
      setNotice(`Погода обновлена, но history недоступна: ${getErrorMessage(error)}`);
    }
  }

  async function loadStation(nextTokens = tokens) {
    if (!nextTokens?.access) return;
    await runTask("station", async () => {
      const params = new URLSearchParams({ station_id: stationId });
      const history = await apiRequest(`/station/history?${params}&limit=100`);
      setStationHistory(history.results || []);

      try {
        const latest = await apiRequest(`/station/latest?${params}`);
        setStationLatest(latest);
      } catch (error) {
        if (error.status === 404) {
          setStationLatest(null);
          return;
        }
        throw error;
      }
    });
  }

  const heroStyle = useMemo(() => {
    const temp = weather?.temperature_c ?? 12;
    const hue = temp < 0 ? 205 : temp > 25 ? 35 : 175;
    return { "--weather-hue": hue };
  }, [weather]);

  const isAuthPage = pathname.includes("login") || pathname.includes("register");

  return (
    <div className={`app-shell ${themeBurst ? "theme-burst" : ""}`} style={heroStyle}>
      <div className="theme-wash" aria-hidden="true" />
      <div className="sky-orbit orbit-a" />
      <div className="sky-orbit orbit-b" />

      <header className="topbar glass-panel">
        <a className="brand" href="/weather" aria-label="DW Weather" onClick={(event) => { event.preventDefault(); navigate("/weather"); }}>
          <span className="brand-mark"><CloudSun size={24} /></span>
          <span>DW Weather</span>
        </a>
        <nav className="nav-links" aria-label="Навигация">
          <a href="/weather" onClick={(event) => { event.preventDefault(); focusSection("weather"); }}>Weather</a>
          <a href={isAuthenticated ? "/weather#charts" : "/login"} onClick={(event) => {
            event.preventDefault();
            if (!isAuthenticated) navigate("/login");
            else focusSection("charts");
          }}>History</a>
          <a href={isAuthenticated ? "/weather#station" : "/login"} onClick={(event) => {
            event.preventDefault();
            if (!isAuthenticated) navigate("/login");
            else focusSection("station");
          }}>Arduino</a>
        </nav>
        <div className="auth-chip">
          <button
            className="icon-button theme-toggle"
            onClick={toggleTheme}
            title={theme === "dark" ? "Light theme" : "Dark theme"}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          {isAuthenticated ? (
            <button className="icon-button" onClick={handleLogout} title="Выйти">
              <LogOut size={18} />
            </button>
          ) : (
            <a className="small-link" href="/login" onClick={(event) => { event.preventDefault(); navigate("/login"); }}>Войти</a>
          )}
        </div>
      </header>

      {isAuthPage ? (
        <main className="auth-page">
          <section className="auth-hero glass-panel reveal is-visible">
            <span className="eyebrow">Account access</span>
            <h1>{authMode === "register" ? "Регистрация" : "Вход"}</h1>
            <p>После авторизации откроются приватные погодные графики и телеметрия Arduino станции.</p>
          </section>
          <AuthPanel
            authMode={authMode}
            authForm={authForm}
            authStatus={authStatus}
            loading={loading.auth}
            setAuthForm={setAuthForm}
            setAuthMode={setAuthMode}
            handleAuth={handleAuth}
            navigate={navigate}
          />
        </main>
      ) : (
      <main className="main-grid">
        <section className={`hero-panel glass-panel reveal is-visible ${sectionPulse === "weather" ? "section-pulse" : ""}`}>
          <div className="hero-copy">
            <span className="eyebrow">Aero weather console</span>
            <h1>{coords.city || "Selected location"}</h1>
            <p>Live API weather, AI outfit hints, history charts and Arduino telemetry in one calm glass workspace.</p>
          </div>

          <form className="search-console" onSubmit={(event) => { event.preventDefault(); loadWeather(); }}>
            <div className="mode-switch" role="tablist" aria-label="Weather search mode">
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
                <input value={coords.city} onChange={(event) => setCoords({ ...coords, city: event.target.value })} placeholder="Moscow" />
              </label>
            ) : (
              <>
                <label>
                  <span>Latitude</span>
                  <input value={coords.lat} onChange={(event) => setCoords({ ...coords, lat: event.target.value })} inputMode="decimal" />
                </label>
                <label>
                  <span>Longitude</span>
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
                <h2>Приватный доступ активен</h2>
              </div>
              <p className="empty-state">Графики истории и Arduino станция доступны ниже.</p>
            </>
          ) : (
            <>
              <div className="panel-title">
                <Lock size={20} />
                <h2>Нужен вход</h2>
              </div>
              <p className="empty-state">Авторизуйтесь, чтобы увидеть history charts и данные Arduino станции.</p>
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

        <section className={`charts-section glass-panel reveal ${sectionPulse === "charts" ? "section-pulse" : ""}`} id="charts">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Protected analytics</span>
              <h2>Weather history</h2>
            </div>
            {!isAuthenticated && <span className="locked-pill">JWT required</span>}
          </div>
          {isAuthenticated ? (
            <div className="chart-grid">
              <LineChart title="Temperature" unit="C" data={weatherHistory} dataKey="temperature_c" color="#18a0fb" />
              <LineChart title="Pressure" unit="hPa" data={weatherHistory} dataKey="pressure_hpa" color="#7c67ff" />
              <LineChart title="Wind" unit="m/s" data={weatherHistory} dataKey="wind_speed_ms" color="#00b894" />
            </div>
          ) : (
            <AccessGate navigate={navigate} text="Графики доступны только авторизованным пользователям." />
          )}
        </section>

        <section className={`station-section glass-panel reveal ${sectionPulse === "station" ? "section-pulse" : ""}`} id="station">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Arduino station</span>
              <h2>Local telemetry</h2>
            </div>
            {isAuthenticated && (
              <div className="station-controls">
                <input value={stationId} onChange={(event) => setStationId(event.target.value)} aria-label="Station ID" />
                <button className="icon-button" onClick={() => loadStation()} title="Обновить станцию">
                  {loading.station ? <RefreshCw className="spin" size={18} /> : <RefreshCw size={18} />}
                </button>
              </div>
            )}
          </div>
          {isAuthenticated ? (
            <>
              <StationLatest reading={stationLatest} />
              <div className="chart-grid station-charts">
                <LineChart title="Station temperature" unit="C" data={stationHistory} dataKey="temperature_c" color="#ff7a59" />
                <LineChart title="Humidity" unit="%" data={stationHistory} dataKey="humidity" color="#18c5c2" />
              </div>
            </>
          ) : (
            <AccessGate navigate={navigate} text="Arduino latest и station history доступны только после входа." />
          )}
        </section>
      </main>
      )}
    </div>
  );
}

function AuthPanel({ authMode, authForm, authStatus, loading, setAuthForm, setAuthMode, handleAuth, navigate }) {
  return (
    <aside className="auth-panel glass-panel reveal is-visible" id={authMode === "register" ? "register" : "login"}>
      <div className="panel-title">
        {authMode === "login" ? <LogIn size={20} /> : <UserPlus size={20} />}
        <h2>{authMode === "login" ? "Вход" : "Регистрация"}</h2>
      </div>
      <form className="auth-form" onSubmit={handleAuth}>
        <input value={authForm.username} onChange={(event) => setAuthForm({ ...authForm, username: event.target.value })} placeholder="username" autoComplete="username" />
        {authMode === "register" && (
          <input value={authForm.email} onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })} placeholder="email" type="email" autoComplete="email" />
        )}
        <input value={authForm.password} onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })} placeholder="password" type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} />
        <button className="primary-button" type="submit" disabled={loading}>
          {loading ? <RefreshCw className="spin" size={18} /> : authMode === "login" ? <LogIn size={18} /> : <UserPlus size={18} />}
          {authMode === "login" ? "Войти" : "Создать"}
        </button>
      </form>
      <button className="text-button" onClick={() => {
        const nextMode = authMode === "login" ? "register" : "login";
        setAuthMode(nextMode);
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

function WeatherCard({ weather }) {
  return (
    <article className="weather-card glass-panel reveal">
      <div className="panel-title">
        <Thermometer size={20} />
        <h2>Current API weather</h2>
      </div>
      <div className="temperature-display">{formatNumber(weather?.temperature_c)}<span>C</span></div>
      <div className="metric-list">
        <Metric icon={<Waves size={18} />} label="Pressure" value={`${formatNumber(weather?.pressure_hpa, 0)} hPa`} />
        <Metric icon={<Wind size={18} />} label="Wind" value={`${formatNumber(weather?.wind_speed_ms)} m/s`} />
        <Metric icon={<Droplets size={18} />} label="Precipitation" value={`${formatNumber(weather?.precipitation_mm)} mm`} />
        <Metric icon={<MapPin size={18} />} label="Source" value={weather?.source || "—"} />
      </div>
      <footer className="card-footer">
        <span>{formatDate(weather?.observed_at)}</span>
        <span className="cache-pill">{weather?.cache_status || "ready"}</span>
      </footer>
    </article>
  );
}

function OutfitCard({ outfit }) {
  return (
    <article className="outfit-card glass-panel reveal">
      <div className="panel-title">
        <Sparkles size={20} />
        <h2>AI outfit</h2>
      </div>
      <p>{outfit?.recommendation || "Рекомендация появится после первого погодного запроса."}</p>
      <footer className="card-footer">
        <span>{outfit?.model || "openrouter/free"}</span>
        <span className="cache-pill">{outfit?.source || "waiting"}</span>
      </footer>
    </article>
  );
}

function StationLatest({ reading }) {
  if (!reading) {
    return (
      <div className="station-empty">
        <Cpu size={22} />
        <div>
          <strong>Нет latest reading</strong>
          <p>Backend вернул пустую Arduino историю. Отправьте тестовый `POST /api/station/readings`, и здесь появятся live-метрики.</p>
        </div>
      </div>
    );
  }

  const items = [
    ["Temp", `${formatNumber(reading?.temperature_c)} C`, <Thermometer size={18} />],
    ["Humidity", `${formatNumber(reading?.humidity, 0)}%`, <Droplets size={18} />],
    ["Pressure", `${formatNumber(reading?.pressure_hpa, 0)} hPa`, <Waves size={18} />],
    ["Wind", `${formatNumber(reading?.wind_speed_ms)} m/s`, <Wind size={18} />],
  ];

  return (
    <div className="station-latest">
      {items.map(([label, value, icon]) => (
        <Metric key={label} icon={icon} label={label} value={value} />
      ))}
      <Metric icon={<Cpu size={18} />} label="Observed" value={formatDate(reading?.observed_at)} />
      <Metric icon={<Activity size={18} />} label="Source" value={reading?.data_source || "—"} />
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
