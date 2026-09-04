(() => {
  "use strict";

  const storageKey = "workspace-theme";
  const systemQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const safeStorageGet = (key) => {
    try {
      return window.localStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  };
  const safeStorageSet = (key, value) => {
    try {
      window.localStorage.setItem(key, value);
    } catch (_error) {
      // Theme remains active for this page when storage is unavailable.
    }
  };
  const storedTheme = safeStorageGet("workspace-theme");
  let theme = storedTheme === "dark" || storedTheme === "light"
    ? storedTheme
    : (systemQuery.matches ? "dark" : "light");
  let themeStore = null;

  const applyTheme = (nextTheme, announce = false) => {
    theme = nextTheme;
    if (themeStore) themeStore.current = theme;
    document.documentElement.dataset.theme = theme;
    // Keep legacy framework utilities in sync with the workspace theme.
    document.documentElement.dataset.mode = theme;
    document.documentElement.style.colorScheme = theme;
    const status = document.querySelector("[data-theme-status]");
    if (status) {
      status.textContent = theme === "dark" ? "Tema escuro ativado" : "Tema claro ativado";
    }
    const icon = document.querySelector("[data-theme-icon]");
    if (icon) icon.textContent = theme === "dark" ? "☀" : "◐";
    if (announce) {
      document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
    }
  };

  applyTheme(theme);

  const toggleTheme = () => {
    const nextTheme = theme === "dark" ? "light" : "dark";
    safeStorageSet(storageKey, nextTheme);
    applyTheme(nextTheme, true);
  };

  // Delegate so the toggle works regardless of Alpine/CSP or render timing.
  document.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-theme-toggle]")) toggleTheme();
  });

  document.addEventListener("alpine:init", () => {
    themeStore = {
      current: theme,
      toggle() {
        const nextTheme = theme === "dark" ? "light" : "dark";
        safeStorageSet(storageKey, nextTheme);
        applyTheme(nextTheme, true);
      },
    };
    window.Alpine.store("theme", themeStore);
    themeStore = window.Alpine.store("theme");
  });

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(theme);
  });

  systemQuery.addEventListener("change", (event) => {
    if (safeStorageGet(storageKey)) return;
    applyTheme(event.matches ? "dark" : "light", true);
  });
})();
