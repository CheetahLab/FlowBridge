export interface DeviceConfig {
  sn: string;
  name: string;
  model?: string;
  // vom Backend ergänzt (modellabhängig)
  controllable?: boolean;
  support_level?: string; // "verified" | "documented" | "none"
  charge_watts_steps?: number[];
  /** Felder, die das Modell meldet, aber nicht annimmt - anzeigen statt anbieten. */
  readonly_fields?: string[];
}

export interface DiscoveredDevice {
  sn: string;
  model: string;
  online: boolean;
  controllable: boolean;
}

export interface EcoFlowConfig {
  access_key: string;
  secret_key: string;
  devices: DeviceConfig[];
}

export interface MqttConfig {
  host: string;
  port: number;
  client_id: string;
  /** Was FlowBridge verwendet, wenn client_id leer bleibt - nur zur Anzeige. */
  client_id_auto?: string;
  username: string;
  password: string;
  base_topic: string;
  retain: boolean;
  poll_interval_seconds: number;
}

export interface UiConfig {
  language: "de" | "en";
  theme: "dark" | "light";
}

export interface AppConfig {
  ecoflow: EcoFlowConfig;
  mqtt: MqttConfig;
  ui: UiConfig;
  // Erlaubte Stufen der AC-Ladeleistung, kommen vom Backend, damit Regler und
  // serverseitige Prüfung nicht auseinanderlaufen.
  charge_watts_steps?: number[];
}

// Spiegelt src/device.py normalize_quota() – Felder sind optional,
// weil je nach Gerätemodell manche fehlen (siehe docs/quota-fields-river2.md).
export interface DeviceStatus {
  sn: string;
  online?: boolean | null;
  last_update?: string;
  error?: string;
  soc_percent?: number;
  backup_reserve_percent?: number;
  backup_reserve_enabled?: number;
  ac_watts_in?: number;
  dc_watts_in?: number;
  watts_out?: number;
  ac_watts_out?: number;
  battery_temp_c?: number;
  discharge_remain_min?: number;
  charge_remain_min?: number;
  battery_watts_in?: number;
  battery_watts_out?: number;
  battery_soc_percent?: number;
  ac_output_enabled?: number;
  ac_output_voltage?: number;
  ac_output_freq_hz?: number;
  xboost_enabled?: number;
  car_output_enabled?: number;
  car_watts?: number;
  usb1_watts?: number;
  typec1_watts?: number;
  typec_charge_watts?: number;
  // Vom Gerät gemeldeter Sollwert (z.B. DELTA 2) - verlässlicher als der
  // gemerkte, aber nicht jedes Modell liefert ihn.
  charge_power_watts?: number;
  charge_paused?: number;
  // Sollwert, den FlowBridge zuletzt gesetzt hat - Rückfallebene für Modelle
  // wie das River 2 Pro, die ihn nicht zurückgeben.
  charge_power_watts_set?: number;
  ac_charging_enabled_set?: boolean;
  charge_limit_percent?: number;
  discharge_limit_percent?: number;
  cycles?: number;
  // Rohwerte nach Modul gruppiert (PD, BMS, EMS, INV, MPPT) für die Kontroll-Tabs
  _modules?: Record<string, Record<string, unknown>>;
  // Sekunden seit der letzten Push-Nachricht. Fehlt, solange seit dem Start
  // noch nie eine kam. Kommt nur über /api/state, bewusst nicht über MQTT -
  // siehe _stille_sekunden() im Backend.
  silence_seconds?: number;
}

export type DeviceStateMap = Record<string, DeviceStatus>;

export interface HistoryPoint {
  t: number; // Sekunden seit Epoch
  soc_percent?: number;
  ac_watts_in?: number;
  dc_watts_in?: number;
  battery_watts_in?: number;
  watts_out?: number;
  ac_watts_out?: number;
}

export interface History {
  sn: string;
  interval_seconds: number;
  fields: string[];
  points: HistoryPoint[];
}

export interface Health {
  ecoflow_broker: { configured: boolean; connected: boolean };
  local_broker: { configured: boolean; connected: boolean; host: string };
  devices: { configured: number; online: number; offline: number; unknown: number };
}

/** Zustaende der Update-Pruefung. "unknown" ist der ehrliche Startwert:
 *  solange keine Quelle eingerichtet ist, weiss FlowBridge nicht, ob es
 *  aktuell ist - und "aktuell" zu behaupten waere schlimmer als das
 *  zuzugeben. */
export type UpdateStatus = "unknown" | "current" | "update";

export interface VersionInfo {
  version: string;
  update: {
    status: UpdateStatus;
    current: string;
    latest: string | null;
    detail: string | null;
  };
}

export interface AuthState {
  configured: boolean;
  authenticated: boolean;
  min_length: number;
  /** Grund im Klartext, falls der Datenordner nicht beschreibbar ist. */
  storage_error?: string | null;
}

/** Zustand des Feldinventars - Kurzfassung fuer die Kachel. */
export interface AnalysisState {
  enabled: boolean;
  /** Wann die Aufzeichnung begonnen hat (ISO), null wenn nie eingeschaltet. */
  started: string | null;
  devices: number;
  fields: number;
  events: number;
  size_bytes: number;
  /** Laufende Fassung – für den Betreff der Einsende-Mail. */
  version?: string;
}

export interface DiagnosticsState {
  enabled: boolean;
  size_bytes: number;
  path: string;
  buffered_lines: number;
  /** Laufende Fassung – für den Betreff der Einsende-Mail. */
  version?: string;
}
