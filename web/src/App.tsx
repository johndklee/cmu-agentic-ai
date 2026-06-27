import { useEffect, useState } from "react";
import { fetchPreferences } from "./api";
import { DigestPage } from "./pages/DigestPage";
import { SettingsPage } from "./pages/SettingsPage";
import "./App.css";

export default function App() {
  const [showSettings, setShowSettings] = useState(false);
  const [contextRefresh, setContextRefresh] = useState(0);
  const [userName, setUserName] = useState("");

  useEffect(() => {
    fetchPreferences().then((p) => setUserName(p.user_name ?? "")).catch(() => {});
  }, [contextRefresh]);

  function handleBack() {
    setShowSettings(false);
    setContextRefresh((n) => n + 1);
  }

  const navTitle = userName ? `Daily Digest for ${userName}` : "Daily Digest";

  return (
    <div className="app">
      <nav className="nav">
        <span className="nav-title">{navTitle}</span>
      </nav>
      <main>
        {showSettings
          ? <SettingsPage onBack={handleBack} onPreferencesSaved={() => setContextRefresh((n) => n + 1)} />
          : <DigestPage onEditSettings={() => setShowSettings(true)} contextRefresh={contextRefresh} />}
      </main>
    </div>
  );
}
