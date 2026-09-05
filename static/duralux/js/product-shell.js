(() => {
  "use strict";

  const root = document.documentElement;
  const safeStorageGet = (key) => {
    try {
      return localStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  };
  const safeStorageSet = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch (_error) {
      // The selected theme still applies for the current document.
    }
  };
  const storedTheme = safeStorageGet("product-theme");
  const preferredDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const initialTheme = storedTheme || (preferredDark ? "dark" : "light");
  root.dataset.bsTheme = initialTheme;
  root.dataset.theme = initialTheme;
  root.style.colorScheme = initialTheme;

  const applyBranding = () => {
    const primary = document.body.dataset.clinicPrimary;
    const secondary = document.body.dataset.clinicSecondary;
    if (primary) root.style.setProperty("--clinic-primary", primary);
    if (secondary) root.style.setProperty("--clinic-secondary", secondary);

    document.querySelectorAll("[data-brand-preview]").forEach((preview) => {
      const previewPrimary = preview.dataset.brandPreviewPrimary;
      const previewSecondary = preview.dataset.brandPreviewSecondary;
      if (previewPrimary) preview.style.setProperty("--preview-primary", previewPrimary);
      if (previewSecondary) preview.style.setProperty("--preview-secondary", previewSecondary);
    });
  };

  const focusableElements = (container) =>
    Array.from(
      container.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => !element.hidden && element.offsetParent !== null);

  document.addEventListener("DOMContentLoaded", () => {
    applyBranding();

    const openButton = document.querySelector("[data-sidebar-open]");
    const closeButton = document.querySelector("[data-sidebar-close]");
    const sidebar = document.querySelector("[data-mobile-sidebar]");
    const overlay = document.querySelector("[data-sidebar-overlay]");

    const closeSidebar = () => {
      if (!sidebar || sidebar.hidden) return;
      sidebar.hidden = true;
      if (overlay) overlay.hidden = true;
      openButton?.setAttribute("aria-expanded", "false");
      root.classList.remove("product-scroll-locked");
      openButton?.focus();
    };

    const openSidebar = () => {
      if (!sidebar) return;
      sidebar.hidden = false;
      if (overlay) overlay.hidden = false;
      openButton?.setAttribute("aria-expanded", "true");
      root.classList.add("product-scroll-locked");
      closeButton?.focus();
    };

    openButton?.addEventListener("click", openSidebar);
    closeButton?.addEventListener("click", closeSidebar);
    overlay?.addEventListener("click", closeSidebar);
    const desktopLayout = window.matchMedia("(min-width: 1200px)");
    desktopLayout.addEventListener("change", (event) => {
      if (event.matches) closeSidebar();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeSidebar();
      if (event.key !== "Tab" || !sidebar || sidebar.hidden) return;
      const focusable = focusableElements(sidebar);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    document.querySelectorAll("[data-copy-target]").forEach((button) => {
      button.addEventListener("click", async () => {
        const targetId = button.dataset.copyTarget;
        const target = targetId ? document.getElementById(targetId) : null;
        const status = button.parentElement?.querySelector("[data-copy-status]");
        if (!target || !status) return;
        try {
          await navigator.clipboard.writeText(target.textContent.trim());
          status.textContent = "Chave copiada.";
        } catch (_error) {
          status.textContent = "Não foi possível copiar. Selecione a chave manualmente.";
        }
      });
    });

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const next = root.dataset.bsTheme === "dark" ? "light" : "dark";
        root.dataset.bsTheme = next;
        root.dataset.theme = next;
        root.style.colorScheme = next;
        safeStorageSet("product-theme", next);
        window.dispatchEvent(new CustomEvent("themechange", { detail: { theme: next } }));
        const status = button.querySelector("[data-theme-status]");
        if (status) status.textContent = next === "dark" ? "Tema escuro" : "Tema claro";
      });
    });
  });
})();
