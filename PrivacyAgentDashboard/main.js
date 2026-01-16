let allSettings = [];
let state = {
  platform: "all",
  category: "all",
  flaggedOnly: true,
  selectedSetting: null
};

d3.csv("dashboard_data.csv", d => ({
  ...d,
  flagged: d.flagged === "true",
  clicks: +d.clicks
})).then(data => {
  allSettings = data;

  populateDropdowns();
  updateSummary();
  renderSettingsList();
  renderRecsList();
});

function populateDropdowns() {
  const platforms = Array.from(new Set(allSettings.map(d => d.platform)));
  const categories = Array.from(new Set(allSettings.map(d => d.category)));

  const platformSelect = d3.select("#platformSelect");
  const categorySelect = d3.select("#categorySelect");

  platforms.forEach(p => {
    platformSelect.append("option")
      .attr("value", p)
      .text(p);
  });

  categories.forEach(c => {
    categorySelect.append("option")
      .attr("value", c)
      .text(c);
  });

  platformSelect.on("change", e => {
    state.platform = e.target.value;
    renderSettingsList();
    updateSummary();
  });

  categorySelect.on("change", e => {
    state.category = e.target.value;
    renderSettingsList();
    updateSummary();
  });

  d3.select("#flaggedOnly").on("change", e => {
    state.flaggedOnly = e.target.checked;
    renderSettingsList();
    updateSummary();
  });
}

function getFilteredSettings() {
  return allSettings.filter(d => {
    if (state.platform !== "all" && d.platform !== state.platform) return false;
    if (state.category !== "all" && d.category !== state.category) return false;
    if (state.flaggedOnly && !d.flagged) return false;
    return true;
  });
}

function renderSettingsList() {
  const settings = getFilteredSettings();

  const list = d3.select("#settingsList");
  list.selectAll("li").remove();

  list.selectAll("li")
    .data(settings, d => d.setting_id)
    .enter()
    .append("li")
    .html(d => `
      <strong>${d.title}</strong><br>
      <small>${d.platform} • ${d.category}</small>
      ${d.flagged ? " ⚠️" : ""}
    `)
    .on("click", (_, d) => {
      state.selectedSetting = d;
      renderSettingDetail();
    });
}

function renderRecsList() {
  const settings = getFilteredSettings();

  const list = d3.select("#recsList");
  list.selectAll("li").remove();

  list.selectAll("li")
    .data(settings, d => d.setting_id)
    .enter()
    .append("li")
    .html(d => `
      <strong>${d.title}</strong><br>
      <small>${d.platform} • ${d.category}</small>
      ${d.flagged ? " ⚠️" : ""}
    `)
    .on("click", (_, d) => {
      state.selectedSetting = d;
      renderSettingDetail();
    });
}

function updateSummary() {
  const filtered = getFilteredSettings();

  d3.select("#statSettings").text(filtered.length);
  d3.select("#statFlags").text(filtered.filter(d => d.flagged).length);
  d3.select("#statChanges").text(
    filtered.filter(d => d.current !== d.recommended).length
  );

  const successRate = Math.round(
    (filtered.filter(d => d.current !== d.recommended).length / filtered.length || 0) * 100
  );

  d3.select("#statSuccess").text(`${successRate}%`);
}

function renderSettingDetail() {
  const detail = d3.select("#settingDetail");
  
  if (!state.selectedSetting) {
    detail.html("<p>Select a setting to view details.</p>");
    return;
  }

  const s = state.selectedSetting;
  detail.html(`
    <h3>${s.title}</h3>
    <p><strong>Platform:</strong> ${s.platform}</p>
    <p><strong>Category:</strong> ${s.category}</p>
    <p><strong>Current Value:</strong> ${s.current || "N/A"}</p>
    <p><strong>Recommended:</strong> ${s.recommended || "N/A"}</p>
    ${s.flagged ? "<p><strong>⚠️ Flagged as high-risk</strong></p>" : ""}
    ${s.clicks ? `<p><strong>Navigation clicks:</strong> ${s.clicks}</p>` : ""}
    ${s.description ? `<p><strong>Description:</strong> ${s.description}</p>` : ""}
  `);
}
