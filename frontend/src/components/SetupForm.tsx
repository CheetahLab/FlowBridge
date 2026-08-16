import { useState } from "react";
import { discoverDevices, saveSetup, testConnection } from "../api";
import type { Strings } from "../i18n";
import type { AppConfig, DeviceConfig } from "../types";

interface Props {
  t: Strings;
  config: AppConfig;
  language: string;
  theme: string;
  onSaved: () => void;
}

// Vom EisBaer vorgegeben, nicht vom MQTT-Standard. Serverseitig gilt
// dieselbe Grenze - das Formular ist nur die freundlichere Haelfte davon.
const MIN_CLIENT_ID_LAENGE = 10;

export default function SetupForm({ t, config, language, theme, onSaved }: Props) {
  const [accessKey, setAccessKey] = useState(config.ecoflow.access_key);
  const [secretKey, setSecretKey] = useState(config.ecoflow.secret_key);
  const [mqttHost, setMqttHost] = useState(config.mqtt.host);
  const [mqttPort, setMqttPort] = useState(config.mqtt.port || 1883);
  const [mqttClientId, setMqttClientId] = useState(config.mqtt.client_id ?? "");
  const [mqttUsername, setMqttUsername] = useState(config.mqtt.username);
  const [mqttPassword, setMqttPassword] = useState(config.mqtt.password);
  const [devices, setDevices] = useState<DeviceConfig[]>(
    config.ecoflow.devices.length ? config.ecoflow.devices : [{ sn: "", name: "" }]
  );

  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const clientIdZuKurz =
    mqttClientId.trim().length > 0 && mqttClientId.trim().length < MIN_CLIENT_ID_LAENGE;

  function updateDevice(index: number, patch: Partial<DeviceConfig>) {
    setDevices((prev) => prev.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  function addDevice() {
    setDevices((prev) => [...prev, { sn: "", name: "" }]);
  }

  /** Geräte aus dem EcoFlow-Konto holen - erspart das Abtippen der Seriennummer
      und liefert das Modell mit, statt es auswählen zu lassen. */
  async function handleDiscover() {
    setDiscovering(true);
    setDiscoverError(null);
    try {
      const { devices: gefunden } = await discoverDevices(accessKey, secretKey);
      setDevices((prev) => {
        // Bereits eingetragene Geräte behalten (inkl. selbst vergebener Namen),
        // nur Modell nachtragen und neue ergänzen.
        const bekannt = new Map(prev.filter((d) => d.sn.trim()).map((d) => [d.sn.trim(), d]));
        for (const g of gefunden) {
          const alt = bekannt.get(g.sn);
          bekannt.set(g.sn, { sn: g.sn, name: alt?.name || g.model, model: g.model });
        }
        return [...bekannt.values()];
      });
    } catch (err) {
      setDiscoverError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiscovering(false);
    }
  }

  function removeDevice(index: number) {
    setDevices((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleTest() {
    setTestStatus(t.testing);
    setTestError(null);
    try {
      const firstSn = devices.find((d) => d.sn.trim())?.sn.trim() ?? "";
      const result = await testConnection({ access_key: accessKey, secret_key: secretKey, sn: firstSn });
      setTestStatus(
        `${t.testOk} (${result.ecoflow_broker}` +
          (result.device_fields !== undefined ? `, ${result.device_fields} Felder` : "") +
          ")"
      );
    } catch (err) {
      setTestStatus(null);
      setTestError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      await saveSetup({
        access_key: accessKey,
        secret_key: secretKey,
        mqtt_host: mqttHost,
        mqtt_port: mqttPort,
        mqtt_client_id: mqttClientId.trim(),
        mqtt_username: mqttUsername,
        mqtt_password: mqttPassword,
        devices: devices
          .filter((d) => d.sn.trim())
          .map((d) => ({ sn: d.sn.trim(), name: d.name.trim(), model: d.model ?? "" })),
        language,
        theme,
      });
      onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fb-card fb-card-wide">
      <h2>{t.setupTitle}</h2>
      <p className="fb-muted">{t.setupHint}</p>

      <label className="fb-field">
        <span>{t.accessKey}</span>
        <input value={accessKey} onChange={(e) => setAccessKey(e.target.value)} autoComplete="off" />
      </label>
      <label className="fb-field">
        <span>{t.secretKey}</span>
        <input value={secretKey} onChange={(e) => setSecretKey(e.target.value)} autoComplete="off" />
      </label>

      <h3>{t.devices}</h3>
      <p className="fb-muted">{t.discoverHint}</p>
      {devices.map((device, i) => (
        <div key={i}>
          <div className="fb-device-row">
            <input
              placeholder={t.deviceSn}
              value={device.sn}
              onChange={(e) => updateDevice(i, { sn: e.target.value })}
            />
            <input
              placeholder={t.deviceName}
              value={device.name}
              onChange={(e) => updateDevice(i, { name: e.target.value })}
            />
            <button type="button" className="fb-toggle" onClick={() => removeDevice(i)}>
              {t.removeDevice}
            </button>
          </div>
          {device.model && (
            <p className="fb-muted fb-device-model">
              {device.model}
              {device.controllable === false && ` · ${t.monitorOnly}`}
            </p>
          )}
        </div>
      ))}
      <div className="fb-actions">
        <button
          type="button"
          className="fb-toggle fb-toggle-primary"
          onClick={handleDiscover}
          disabled={discovering || !accessKey || !secretKey}
        >
          {discovering ? t.discovering : t.discoverDevices}
        </button>
        <button type="button" className="fb-toggle" onClick={addDevice}>
          + {t.addDevice}
        </button>
      </div>
      {discoverError && <p className="fb-status-error">{discoverError}</p>}

      <h3>MQTT</h3>
      <label className="fb-field">
        <span>{t.mqttHost}</span>
        <input value={mqttHost} onChange={(e) => setMqttHost(e.target.value)} />
      </label>
      <label className="fb-field">
        <span>{t.mqttPort}</span>
        <input
          type="number"
          value={mqttPort}
          onChange={(e) => setMqttPort(parseInt(e.target.value, 10) || 1883)}
        />
      </label>
      <label className="fb-field">
        <span>{t.mqttClientId}</span>
        <input
          value={mqttClientId}
          onChange={(e) => setMqttClientId(e.target.value)}
          placeholder={config.mqtt.client_id_auto ?? ""}
          autoComplete="off"
        />
      </label>
      <p className="fb-muted fb-field-hint">
        {mqttClientId.trim() && mqttClientId.trim().length < MIN_CLIENT_ID_LAENGE
          ? t.mqttClientIdTooShort
          : t.mqttClientIdHint}
      </p>

      <label className="fb-field">
        <span>{t.mqttUsername}</span>
        <input value={mqttUsername} onChange={(e) => setMqttUsername(e.target.value)} autoComplete="off" />
      </label>
      <label className="fb-field">
        <span>{t.mqttPassword}</span>
        <input value={mqttPassword} onChange={(e) => setMqttPassword(e.target.value)} autoComplete="off" />
      </label>

      <div className="fb-actions">
        <button type="button" className="fb-toggle" onClick={handleTest} disabled={!accessKey || !secretKey}>
          {t.testConnection}
        </button>
        <button
          type="button"
          className="fb-toggle fb-toggle-primary"
          onClick={handleSave}
          disabled={
            saving ||
            !accessKey ||
            !secretKey ||
            !mqttHost ||
            clientIdZuKurz
          }
        >
          {saving ? t.saving : t.save}
        </button>
      </div>

      {testStatus && <p className="fb-status-ok">{testStatus}</p>}
      {testError && <p className="fb-status-error">{testError}</p>}
      {saveError && <p className="fb-status-error">{saveError}</p>}
    </div>
  );
}
