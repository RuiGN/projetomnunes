(() => {
  "use strict";

  const canonicalize = (input) => input.value.replace(/\D/g, "");

  const formatPhone = (digits) => {
    const value = digits.slice(0, 11);
    if (value.length <= 2) return value;
    if (value.length <= 6) return `(${value.slice(0, 2)}) ${value.slice(2)}`;
    if (value.length <= 10) {
      return `(${value.slice(0, 2)}) ${value.slice(2, 6)}-${value.slice(6)}`;
    }
    return `(${value.slice(0, 2)}) ${value.slice(2, 7)}-${value.slice(7)}`;
  };

  const formatDocument = (digits) => {
    const value = digits.slice(0, 14);
    if (value.length <= 11) {
      return value
        .replace(/^(\d{3})(\d)/, "$1.$2")
        .replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
        .replace(/\.(\d{3})(\d)/, ".$1-$2");
    }
    return value
      .replace(/^(\d{2})(\d)/, "$1.$2")
      .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
      .replace(/\.(\d{3})(\d)/, ".$1/$2")
      .replace(/(\/\d{4})(\d)/, "$1-$2");
  };

  const initializeForm = (form) => {
    let dirty = false;
    const submitButton = form.querySelector("[data-submit-button]");
    const maskedInputs = form.querySelectorAll("[data-mask]");

    maskedInputs.forEach((input) => {
      const updateMask = () => {
        const maxDigits = input.dataset.mask === "phone" ? 11 : 14;
        const canonicalValue = canonicalize(input).slice(0, maxDigits);
        input.dataset.canonicalValue = canonicalValue;
        input.value = input.dataset.mask === "phone"
          ? formatPhone(canonicalValue)
          : formatDocument(canonicalValue);
      };
      input.addEventListener("input", updateMask);
      updateMask();
    });

    form.addEventListener("input", () => { dirty = true; });
    form.addEventListener("change", () => { dirty = true; });
    form.addEventListener("submit", (event) => {
      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }
      form.setAttribute("data-submitting", "true");
      dirty = false;
      maskedInputs.forEach((input) => {
        const canonicalValue = input.dataset.canonicalValue ?? canonicalize(input);
        input.value = canonicalValue;
      });
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.setAttribute("aria-disabled", "true");
      }
    });

    form.querySelectorAll("[data-destructive-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const accepted = window.confirm(button.dataset.confirmation);
        if (accepted) form.requestSubmit(button);
      });
    });

    window.addEventListener("beforeunload", (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = form.dataset.dirtyMessage;
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-form-guard]").forEach(initializeForm);
    document.querySelectorAll("[data-brand-preview]").forEach((preview) => {
      const primary = document.querySelector("[data-brand-primary-input]");
      const secondary = document.querySelector("[data-brand-secondary-input]");
      const logo = document.querySelector("[data-brand-logo-input]");
      const previewLogo = preview.querySelector("[data-brand-preview-logo]");
      const updateColors = () => {
        if (primary?.value) preview.style.setProperty("--clinic-primary", primary.value);
        if (secondary?.value) preview.style.setProperty("--clinic-secondary", secondary.value);
      };
      primary?.addEventListener("input", updateColors);
      secondary?.addEventListener("input", updateColors);
      logo?.addEventListener("change", () => {
        const file = logo.files?.[0];
        if (!file || !previewLogo) return;
        previewLogo.src = URL.createObjectURL(file);
        previewLogo.classList.remove("hidden", "d-none");
      });
      updateColors();
    });
    document.querySelector("[aria-invalid=\"true\"]")?.focus();
  });

  window.addEventListener("pageshow", () => {
    document.querySelectorAll("[data-form-guard]").forEach((form) => {
      form.removeAttribute("data-submitting");
      const submitButton = form.querySelector("[data-submit-button]");
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.removeAttribute("aria-disabled");
      }
    });
  });
})();
