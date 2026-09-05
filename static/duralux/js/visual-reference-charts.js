(() => {
  "use strict";

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const charts = [];
  const dateFormatter = new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });

  const semanticColors = () => {
    const styles = getComputedStyle(document.documentElement);
    return {
      brand: styles.getPropertyValue("--product-primary").trim() || "#3454d1",
      text: styles.getPropertyValue("--bs-body-color").trim(),
      muted: styles.getPropertyValue("--bs-secondary-color").trim(),
      border: styles.getPropertyValue("--bs-border-color").trim(),
    };
  };

  const optionsFor = (element) => {
    const colors = semanticColors();
    const categories = JSON.parse(element.dataset.categories || "[]");
    const values = JSON.parse(element.dataset.series || "[]");
    const axisType = element.dataset.axisType || "category";
    const formatDate = (value) => dateFormatter.format(new Date(value));
    return {
      chart: {
        type: "line",
        height: 300,
        toolbar: { show: false },
        animations: { enabled: !reducedMotion.matches },
        foreColor: colors.text,
      },
      colors: [colors.brand],
      series: [{ name: element.dataset.seriesLabel || "Registros", data: values }],
      stroke: { width: 3, curve: "straight" },
      markers: { size: 5 },
      xaxis: {
        type: axisType,
        categories,
        labels: {
          style: { colors: colors.muted },
          formatter: axisType === "datetime" ? formatDate : undefined,
        },
        title: { text: "Período" },
      },
      yaxis: {
        min: 0,
        forceNiceScale: true,
        title: { text: element.dataset.valueLabel || "Registros" },
      },
      grid: { borderColor: colors.border },
      tooltip: {
        x: {
          show: true,
          formatter: axisType === "datetime" ? formatDate : undefined,
        },
      },
      theme: { mode: document.documentElement.dataset.bsTheme || "light" },
      responsive: [
        {
          breakpoint: 640,
          options: { chart: { height: 240 }, markers: { size: 4 } },
        },
      ],
    };
  };

  const initialize = (element) => {
    if (!window.ApexCharts) return;
    const summary = element.closest("[data-chart-block]")?.querySelector("[data-chart-summary]");
    const table = element.closest("[data-chart-block]")?.querySelector("[data-chart-table]");
    const describedBy = [summary?.id, table?.id].filter(Boolean).join(" ");
    element.setAttribute("role", "img");
    element.setAttribute("aria-label", element.dataset.chartLabel || "Gráfico de registros");
    element.setAttribute("aria-describedby", describedBy);
    const chart = new window.ApexCharts(element, optionsFor(element));
    chart.render();
    charts.push({ chart, element });
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-apex-chart]").forEach(initialize);
  });

  document.addEventListener("themechange", () => {
    charts.forEach(({ chart, element }) => chart.updateOptions(optionsFor(element), false, true));
  });
})();
