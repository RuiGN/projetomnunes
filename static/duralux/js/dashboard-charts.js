(() => {
  "use strict";

  const initializeRegistrationChart = () => {
    const source = document.getElementById("registration-series");
    const container = document.getElementById("registrations-chart");
    if (!source || !container || !window.ApexCharts) return;

    let series;
    try {
      series = JSON.parse(source.textContent || "[]");
    } catch (_error) {
      return;
    }

    const chart = new window.ApexCharts(container, {
      chart: { type: "bar", height: 240, toolbar: { show: false } },
      series: [{ name: "Cadastros", data: series.map((item) => item.count) }],
      xaxis: { categories: series.map((item) => item.label) },
      colors: [getComputedStyle(document.documentElement).getPropertyValue("--product-primary").trim()],
      noData: { text: "Sem cadastros no período." },
    });
    chart.render();
  };

  document.addEventListener("DOMContentLoaded", initializeRegistrationChart);
})();
