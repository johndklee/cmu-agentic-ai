import { useEffect, useState } from "react";
import { fetchPreferences, savePreferences, clearMemory, resetAllPreferences, resetDigestPreferences, type Preferences } from "../api";

interface Props {
  onBack: () => void;
  onPreferencesSaved?: () => void;
}

export function SettingsPage({ onBack, onPreferencesSaved }: Props) {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [memoryCleared, setMemoryCleared] = useState(false);
  const [memoryError, setMemoryError] = useState("");
  const [resetMsg, setResetMsg] = useState("");

  useEffect(() => {
    fetchPreferences().then(setPrefs).catch((e) => setError(String(e)));
  }, []);

  async function handleSave() {
    if (!prefs) return;
    try {
      await savePreferences(prefs);
      setSaved(true);
      onPreferencesSaved?.();
      setTimeout(() => setSaved(false), 2000);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function handleClearMemory() {
    if (!window.confirm("Remove all episodic memory? This cannot be undone.")) return;
    try {
      await clearMemory();
      setMemoryCleared(true);
      setTimeout(() => setMemoryCleared(false), 2000);
    } catch (e: unknown) {
      setMemoryError(String(e));
    }
  }

  async function handleResetDigest() {
    if (!window.confirm("Reset digest preferences (feedback history, email toggle, temperature unit)?")) return;
    await resetDigestPreferences();
    setResetMsg("Digest preferences reset.");
    fetchPreferences().then(setPrefs);
    setTimeout(() => setResetMsg(""), 2000);
  }

  async function handleResetAll() {
    if (!window.confirm("Reset ALL preferences to defaults? This cannot be undone.")) return;
    await resetAllPreferences();
    setResetMsg("All preferences reset.");
    fetchPreferences().then(setPrefs);
    setTimeout(() => setResetMsg(""), 2000);
  }

  if (!prefs) return <p>{error || "Loading…"}</p>;

  return (
    <div className="page settings-page">
      <div className="settings-header">
        <h1>Settings</h1>
        <button className="back-btn" onClick={onBack}>← Back</button>
      </div>

      <label>Name
        <input value={prefs.user_name} onChange={(e) => setPrefs({ ...prefs, user_name: e.target.value })} />
      </label>

      <label>Email
        <input value={prefs.user_email} onChange={(e) => setPrefs({ ...prefs, user_email: e.target.value })} />
      </label>

      <label>VIP emails (comma-separated)
        <input
          value={prefs.vip_email_addresses.join(", ")}
          onChange={(e) =>
            setPrefs({ ...prefs, vip_email_addresses: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
          }
        />
      </label>

      <label>Temperature unit
        <select value={prefs.temperature_unit} onChange={(e) => setPrefs({ ...prefs, temperature_unit: e.target.value })}>
          <option value="C">Celsius</option>
          <option value="F">Fahrenheit</option>
        </select>
      </label>

      <label>Preferred location
        <input
          value={prefs.preferred_location_text}
          onChange={(e) => setPrefs({ ...prefs, preferred_location_text: e.target.value })}
        />
      </label>

      <label>Key highlights count (1–8)
        <input
          type="number"
          min={1}
          max={8}
          value={prefs.preferred_highlight_count ?? 5}
          onChange={(e) => {
            const n = parseInt(e.target.value);
            if (!isNaN(n)) setPrefs({ ...prefs, preferred_highlight_count: Math.max(1, Math.min(8, n)) });
          }}
        />
      </label>

      <label className="checkbox-label" title={!prefs.user_email?.trim() ? "Enter your email address above to enable this option" : ""}>
        <input
          type="checkbox"
          checked={prefs.email_daily_digest ?? false}
          disabled={!prefs.user_email?.trim()}
          onChange={(e) => setPrefs({ ...prefs, email_daily_digest: e.target.checked })}
        />
        Send daily digest by email
        {!prefs.user_email?.trim() && (
          <span className="field-hint"> — enter your email above to enable</span>
        )}
      </label>

      <div className="settings-save-row">
        {saved && <span className="saved-msg">Saved!</span>}
        {error && <span className="error">{error}</span>}
        <button className="save-btn" onClick={handleSave}>Save</button>
      </div>

      <div className="reset-section">
        <h2>Reset</h2>
        {resetMsg && <span className="saved-msg">{resetMsg}</span>}
        {memoryCleared && <span className="saved-msg">Memory cleared!</span>}
        {memoryError && <span className="error">{memoryError}</span>}
        <div className="reset-buttons">
          <div className="reset-option">
            <button className="clear-memory-btn" onClick={handleClearMemory}>Remove All Memory</button>
            <p className="reset-desc">Deletes all episodic memory corrections stored in the vector database.</p>
          </div>
          <div className="reset-option">
            <button className="clear-memory-btn" onClick={handleResetDigest}>Reset Digest Preferences</button>
            <p className="reset-desc">Clears feedback history, email toggle, and temperature unit. Preserves identity and location.</p>
          </div>
          <div className="reset-option">
            <button className="clear-memory-btn" onClick={handleResetAll}>Reset All Preferences</button>
            <p className="reset-desc">Resets everything to defaults including identity, location, and all digest settings.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
