import { useEffect, useState } from 'react';
import { Moon, Sun, Bell, RefreshCw, Save, Settings as SettingsIcon } from 'lucide-react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { useTheme } from '../hooks/useTheme';
import { apiClient } from '../api/client';
import type { Settings as SettingsType } from '../types';

export const Settings = () => {
  const { theme, toggleTheme } = useTheme();
  const [settings, setSettings] = useState<SettingsType>({
    theme: 'light',
    notifications_enabled: true,
    auto_scan_enabled: false,
    scan_interval: 3600,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);
      const data = await apiClient.getSettings();
      setSettings(data);
    } catch (err) {
      console.error('Failed to load settings:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setMessage(null);
      await apiClient.updateSettings(settings);
      setMessage({ type: 'success', text: 'Settings saved successfully!' });
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      console.error('Failed to save settings:', err);
      setMessage({ type: 'error', text: 'Failed to save settings. Please try again.' });
    } finally {
      setSaving(false);
    }
  };

  const handleThemeToggle = () => {
    toggleTheme();
    setSettings((prev) => ({
      ...prev,
      theme: theme === 'light' ? 'dark' : 'light',
    }));
  };

  return (
    <div className="space-y-6 animate-fade-in max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Settings</h1>
        <p className="text-gray-600 dark:text-gray-400 mt-1">
          Customize your JarvisMax experience
        </p>
      </div>

      {/* Success/Error Message */}
      {message && (
        <div
          className={`p-4 rounded-lg border ${
            message.type === 'success'
              ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-800 dark:text-green-300'
              : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-800 dark:text-red-300'
          }`}
        >
          {message.text}
        </div>
      )}

      {/* Appearance Settings */}
      <Card title="Appearance" subtitle="Customize the look and feel">
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-3">
                {theme === 'dark' ? (
                  <Moon className="w-5 h-5 text-gray-700 dark:text-gray-300" />
                ) : (
                  <Sun className="w-5 h-5 text-gray-700 dark:text-gray-300" />
                )}
                <div>
                  <h3 className="font-medium text-gray-900 dark:text-white">Theme</h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Switch between light and dark mode
                  </p>
                </div>
              </div>
            </div>
            <button
              onClick={handleThemeToggle}
              className={`relative inline-flex h-8 w-14 items-center rounded-full transition-colors ${
                theme === 'dark' ? 'bg-primary-600' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-6 w-6 transform rounded-full bg-white transition-transform ${
                  theme === 'dark' ? 'translate-x-7' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>
      </Card>

      {/* Notification Settings */}
      <Card title="Notifications" subtitle="Manage notification preferences">
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <Bell className="w-5 h-5 text-gray-700 dark:text-gray-300" />
                <div>
                  <h3 className="font-medium text-gray-900 dark:text-white">
                    Enable Notifications
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Receive alerts for important events
                  </p>
                </div>
              </div>
            </div>
            <button
              onClick={() =>
                setSettings((prev) => ({
                  ...prev,
                  notifications_enabled: !prev.notifications_enabled,
                }))
              }
              className={`relative inline-flex h-8 w-14 items-center rounded-full transition-colors ${
                settings.notifications_enabled ? 'bg-primary-600' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-6 w-6 transform rounded-full bg-white transition-transform ${
                  settings.notifications_enabled ? 'translate-x-7' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>
      </Card>

      {/* Automation Settings */}
      <Card title="Automation" subtitle="Configure automated tasks">
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <RefreshCw className="w-5 h-5 text-gray-700 dark:text-gray-300" />
                <div>
                  <h3 className="font-medium text-gray-900 dark:text-white">
                    Auto-scan for Opportunities
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Automatically scan for new opportunities
                  </p>
                </div>
              </div>
            </div>
            <button
              onClick={() =>
                setSettings((prev) => ({
                  ...prev,
                  auto_scan_enabled: !prev.auto_scan_enabled,
                }))
              }
              className={`relative inline-flex h-8 w-14 items-center rounded-full transition-colors ${
                settings.auto_scan_enabled ? 'bg-primary-600' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-6 w-6 transform rounded-full bg-white transition-transform ${
                  settings.auto_scan_enabled ? 'translate-x-7' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {settings.auto_scan_enabled && (
            <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                Scan Interval (seconds)
              </label>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="300"
                  max="86400"
                  step="300"
                  value={settings.scan_interval}
                  onChange={(e) =>
                    setSettings((prev) => ({
                      ...prev,
                      scan_interval: parseInt(e.target.value),
                    }))
                  }
                  className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-lg appearance-none cursor-pointer accent-primary-600"
                />
                <span className="text-sm font-medium text-gray-900 dark:text-white min-w-[100px]">
                  {settings.scan_interval >= 3600
                    ? `${(settings.scan_interval / 3600).toFixed(1)} hours`
                    : `${settings.scan_interval} seconds`}
                </span>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                How often the system should automatically scan for new opportunities
              </p>
            </div>
          )}
        </div>
      </Card>

      {/* System Information */}
      <Card title="System Information" subtitle="About JarvisMax AI OS">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Version</p>
              <p className="font-medium text-gray-900 dark:text-white">1.0.0</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">API Endpoint</p>
              <p className="font-medium text-gray-900 dark:text-white">
                http://localhost:8000/api/v2
              </p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Environment</p>
              <p className="font-medium text-gray-900 dark:text-white">Production</p>
            </div>
            <div>
              <p className="text-sm text-gray-600 dark:text-gray-400">Build</p>
              <p className="font-medium text-gray-900 dark:text-white">
                {new Date().toISOString().split('T')[0]}
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* Save Button */}
      <div className="flex items-center gap-4">
        <Button onClick={handleSave} loading={saving} size="lg" className="gap-2">
          <Save className="w-5 h-5" />
          Save Settings
        </Button>
        <Button variant="secondary" onClick={loadSettings} size="lg">
          Reset
        </Button>
      </div>
    </div>
  );
};
