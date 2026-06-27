import { useEffect, useState } from "react";
import { fetchPreferences, type Preferences } from "../api";

interface Props {
  onEdit: () => void;
  refresh?: number;
}

export function PreferencesPanel({ onEdit, refresh = 0 }: Props) {
  const [prefs, setPrefs] = useState<Preferences | null>(null);

  useEffect(() => {
    fetchPreferences().then(setPrefs).catch(() => {});
  }, [refresh]);

  if (!prefs) return null;

  const rows: [string, string][] = [
    ["Name", prefs.user_name || "—"],
    ["Email", prefs.user_email || "—"],
    ["VIP emails", prefs.vip_email_addresses.join(", ") || "—"],
    ["Temperature unit", prefs.temperature_unit || "—"],
    ["Preferred location", prefs.preferred_location_text || "—"],
    ["Key highlights", `${prefs.preferred_highlight_count ?? 5}`],
    ["Email digest", prefs.email_daily_digest === true ? "Enabled" : prefs.email_daily_digest === false ? "Disabled" : "Not set"],
  ];

  return (
    <div className="prefs-panel">
      <div className="prefs-header">
        <h2>Current Preferences</h2>
        <button className="prefs-edit-btn" onClick={onEdit}>Edit</button>
      </div>
      <table className="prefs-table">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td className="prefs-label">{label}</td>
              <td className="prefs-value">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {prefs.digest_preferences_summary && (
        <p className="prefs-summary">{prefs.digest_preferences_summary}</p>
      )}
    </div>
  );
}
