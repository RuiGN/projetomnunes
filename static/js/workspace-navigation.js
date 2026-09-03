document.addEventListener("alpine:init", () => {
  window.Alpine.data("workspaceNavigation", () => ({
    sidebarOpen: false,

    openSidebar() {
      this.sidebarOpen = true;
      this.$nextTick(() => this.$refs.sidebarClose?.focus());
    },

    closeSidebar() {
      if (!this.sidebarOpen) return;
      this.sidebarOpen = false;
      this.$nextTick(() => this.$refs.sidebarToggle?.focus());
    },

    trapFocus(event) {
      if (!this.sidebarOpen) return;
      const focusable = Array.from(
        this.$refs.mobileSidebar?.querySelectorAll(
          'a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },

    syncScrollLock() {
      document.documentElement.classList.toggle(
        "workspace-scroll-locked",
        this.sidebarOpen,
      );
    },
  }));
});
