import type {
  AppConfig,
  DeviceStateMap,
  DiscoveredDevice,
  Health,
  History,
  VersionInfo,
  AnalysisState,
  AuthState,
  DiagnosticsState,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (res.status === 401) {
    // Sitzung abgelaufen oder Schutz noch nicht eingerichtet. Zentral hier,
    // damit es an JEDER Route bemerkt wird - nicht nur an denen, an die
    // jemand gedacht hat.
    const body = await res.json().catch(() => ({}));
    window.dispatchEvent(
      new CustomEvent("fb-unauthorized", { detail: { setupRequired: !!body.setup_required } })
    );
    throw new Error(body.detail ?? "Nicht angemeldet.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function getConfig(): Promise<AppConfig> {
  return request("/api/config");
}

export function getState(): Promise<DeviceStateMap> {
  return request("/api/state");
}

export function getHealth(): Promise<Health> {
  return request("/api/health");
}

export function getVersion(): Promise<VersionInfo> {
  return request("/api/version");
}

export function getHistory(sn: string, minutes: number): Promise<History> {
  return request(`/api/history/${encodeURIComponent(sn)}?minutes=${minutes}`);
}

export function refreshDevice(sn: string): Promise<{ ok: boolean; fields: number }> {
  return request(`/api/refresh/${encodeURIComponent(sn)}`, { method: "POST" });
}

export interface SetupPayload {
  access_key: string;
  secret_key: string;
  mqtt_host: string;
  mqtt_port: number;
  /** Leer = automatisch (flowbridge-<instanz>). */
  mqtt_client_id: string;
  mqtt_username: string;
  mqtt_password: string;
  devices: { sn: string; name: string; model: string }[];
  language: string;
  theme: string;
}

export function discoverDevices(
  access_key: string,
  secret_key: string
): Promise<{ devices: DiscoveredDevice[] }> {
  return request("/api/setup/discover", {
    method: "POST",
    body: JSON.stringify({ access_key, secret_key }),
  });
}

export function saveSetup(payload: SetupPayload): Promise<{ ok: boolean }> {
  return request("/api/setup", { method: "POST", body: JSON.stringify(payload) });
}

/** Jetzt nachsehen, ohne auf den Takt zu warten. Prueft auch dann, wenn die
 *  Hintergrundpruefung abgeschaltet ist - ein Klick ist eine ausdrueckliche
 *  Handlung, kein stiller Abruf. */
export function checkUpdateNow(): Promise<VersionInfo["update"]> {
  return request("/api/version/check", { method: "POST" });
}

/** Hintergrundpruefung ein-/ausschalten. Der Knopf "Jetzt pruefen" bleibt
 *  davon unberuehrt. */
export function saveUpdateSetting(enabled: boolean): Promise<{ ok: boolean }> {
  return request("/api/update", { method: "POST", body: JSON.stringify({ enabled }) });
}

/** Darstellungs-Vorgabe dieser Installation - gilt fuer jeden Browser, der
 *  FlowBridge zum ersten Mal aufruft. */
export function saveUi(theme: string, language: string): Promise<{ ok: boolean }> {
  return request("/api/ui", {
    method: "POST",
    body: JSON.stringify({ theme, language }),
  });
}

export interface TestPayload {
  access_key: string;
  secret_key: string;
  sn?: string;
}

export function testConnection(
  payload: TestPayload
): Promise<{ ok: boolean; ecoflow_broker: string; device_fields?: number }> {
  return request("/api/setup/test", { method: "POST", body: JSON.stringify(payload) });
}

export function sendCommand(sn: string, property: string, value: string): Promise<{ ok: boolean; data: unknown }> {
  return request("/api/command", { method: "POST", body: JSON.stringify({ sn, property, value }) });
}

export function getAuthState(): Promise<AuthState> {
  return request("/api/auth/state");
}

export function login(password: string): Promise<{ ok: boolean }> {
  return request("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) });
}

export function logout(): Promise<{ ok: boolean }> {
  return request("/api/auth/logout", { method: "POST" });
}

export function setPassword(
  password: string,
  current_password?: string
): Promise<{ ok: boolean }> {
  return request("/api/auth/password", {
    method: "POST",
    body: JSON.stringify({ password, current_password: current_password ?? null }),
  });
}

export function getDiagnostics(): Promise<DiagnosticsState> {
  return request("/api/diagnostics");
}

export function setDiagnostics(enabled: boolean): Promise<DiagnosticsState> {
  return request("/api/diagnostics", { method: "POST", body: JSON.stringify({ enabled }) });
}

export function clearDiagnostics(): Promise<DiagnosticsState> {
  return request("/api/diagnostics", { method: "DELETE" });
}

export function getAnalysis(): Promise<AnalysisState> {
  return request("/api/analysis");
}

export function setAnalysis(enabled: boolean): Promise<AnalysisState> {
  return request("/api/analysis", { method: "POST", body: JSON.stringify({ enabled }) });
}

export function resetAnalysis(): Promise<AnalysisState> {
  return request("/api/analysis", { method: "DELETE" });
}
