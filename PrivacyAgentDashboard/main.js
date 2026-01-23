let allSettings = [];
let jsonData = [];
let state = {
  platform: "all",
  category: "all",
  flaggedOnly: true,
  selectedSetting: null
};

// Load both CSV and JSON data
Promise.all([
  d3.csv("dashboard_data.csv", d => ({
    ...d,
    flagged: d.flagged === "true",
    clicks: +d.clicks
  })),
  d3.json("../database/data/all_platforms_classified.json").catch(err => {
    console.warn("Failed to load JSON data:", err);
    return [];
  })
]).then(([csvData, jsonDataLoaded]) => {
  allSettings = csvData;
  jsonData = jsonDataLoaded || [];

  populateDropdowns();
  populateNetworkPlatforms();
  updateSummary();
  renderSettingsList();
  renderRecsList();
  if (jsonData.length > 0) {
    renderVisualization();
    renderNetworkGraph("all");
  } else {
    d3.select("#compareChart").html("<p style='padding: 20px; color: #666;'>Unable to load visualization data. Make sure all_platforms_classified.json is accessible.</p>");
  }
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

function renderVisualization() {
  if (!jsonData || jsonData.length === 0) return;

  // Process JSON data for visualization
  const platformStats = {};
  const stateStats = {};
  const categoryStats = {};
  const platformStateBreakdown = {};

  jsonData.forEach(entry => {
    const platform = entry.platform || 'unknown';
    const category = entry.category || 'unknown';
    
    // Count settings per platform
    if (!platformStats[platform]) {
      platformStats[platform] = 0;
      platformStateBreakdown[platform] = {};
    }
    platformStats[platform] += (entry.settings || []).length;

    // Count by category
    categoryStats[category] = (categoryStats[category] || 0) + (entry.settings || []).length;

    // Count by state and platform-state breakdown
    (entry.settings || []).forEach(setting => {
      const state = setting.state || 'unknown';
      stateStats[state] = (stateStats[state] || 0) + 1;
      platformStateBreakdown[platform][state] = (platformStateBreakdown[platform][state] || 0) + 1;
    });
  });

  const container = d3.select("#compareChart");
  container.selectAll("*").remove();

  const margin = { top: 20, right: 30, bottom: 80, left: 60 };
  const width = 800 - margin.left - margin.right;
  const height = 400 - margin.top - margin.bottom;

  const svg = container.append("svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  // Create grouped bar chart: platforms vs states
  const platforms = Object.keys(platformStats).sort();
  const states = Object.keys(stateStats)
    .filter(s => !['Not applicable', 'navigational', 'unknown'].includes(s))
    .sort()
    .slice(0, 5); // Top 5 states

  if (platforms.length === 0 || states.length === 0) {
    container.html("<p style='padding: 20px; color: #666;'>No data available for visualization.</p>");
    return;
  }

  // Prepare data for grouped bars
  const data = platforms.map(platform => {
    const total = platformStats[platform];
    const stateCounts = states.map(state => ({
      state: state,
      count: platformStateBreakdown[platform][state] || 0,
      percentage: total > 0 ? ((platformStateBreakdown[platform][state] || 0) / total * 100).toFixed(1) : "0.0"
    }));
    return { platform, total, states: stateCounts };
  });

  // X scale
  const x0 = d3.scaleBand()
    .domain(platforms)
    .range([0, width])
    .paddingInner(0.2);

  const x1 = d3.scaleBand()
    .domain(states)
    .range([0, x0.bandwidth()])
    .padding(0.05);

  // Y scale
  const maxCount = d3.max(data, d => d3.max(d.states, s => s.count));
  const y = d3.scaleLinear()
    .domain([0, maxCount * 1.1])
    .range([height, 0]);

  // Color scale
  const colors = d3.scaleOrdinal()
    .domain(states)
    .range(d3.schemeSet2);

  // X axis
  svg.append("g")
    .attr("transform", `translate(0,${height})`)
    .call(d3.axisBottom(x0))
    .selectAll("text")
    .style("text-anchor", "middle")
    .attr("transform", "rotate(0)")
    .style("font-size", "12px");

  // Y axis
  svg.append("g")
    .call(d3.axisLeft(y))
    .append("text")
    .attr("fill", "#000")
    .attr("transform", "rotate(-90)")
    .attr("y", -40)
    .attr("x", -height / 2)
    .attr("dy", "0.71em")
    .style("text-anchor", "middle")
    .text("Number of Settings");

  // Bars
  const groups = svg.selectAll(".group")
    .data(data)
    .enter().append("g")
    .attr("class", "group")
    .attr("transform", d => `translate(${x0(d.platform)},0)`);

  groups.selectAll("rect")
    .data(d => d.states.map(s => ({ ...s, platform: d.platform })))
    .enter().append("rect")
    .attr("x", d => x1(d.state))
    .attr("y", d => y(d.count))
    .attr("width", x1.bandwidth())
    .attr("height", d => height - y(d.count))
    .attr("fill", d => colors(d.state))
    .on("mouseover", function(event, d) {
      d3.select(this).attr("opacity", 0.7);
      const tooltip = d3.select("body").append("div")
        .attr("class", "tooltip")
        .style("position", "fixed")
        .style("background", "rgba(0,0,0,0.8)")
        .style("color", "white")
        .style("padding", "8px")
        .style("border-radius", "4px")
        .style("pointer-events", "none")
        .style("font-size", "12px")
        .style("z-index", "1000")
        .html(`${d.platform}<br/>${d.state}: ${d.count}<br/>${d.percentage}%`);
    })
    .on("mousemove", function(event) {
      d3.select(".tooltip")
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px");
    })
    .on("mouseout", function() {
      d3.select(this).attr("opacity", 1);
      d3.select(".tooltip").remove();
    });

  // Legend
  const legend = svg.append("g")
    .attr("class", "legend")
    .attr("transform", `translate(${width / 2 - 100},${-10})`);

  const legendItems = legend.selectAll(".legend-item")
    .data(states)
    .enter().append("g")
    .attr("class", "legend-item")
    .attr("transform", (d, i) => `translate(${i * 120}, 0)`);

  legendItems.append("rect")
    .attr("width", 12)
    .attr("height", 12)
    .attr("fill", colors);

  legendItems.append("text")
    .attr("x", 16)
    .attr("y", 9)
    .style("font-size", "11px")
    .text(d => d);

  // Add summary text
  container.append("div")
    .style("margin-top", "10px")
    .style("font-size", "14px")
    .style("color", "#666")
    .html(`<strong>Total Settings:</strong> ${Object.values(platformStats).reduce((a, b) => a + b, 0)} across ${platforms.length} platforms`);
}

function populateNetworkPlatforms() {
  if (!jsonData || jsonData.length === 0) return;
  
  const platforms = Array.from(new Set(jsonData.map(d => d.platform))).sort();
  const select = d3.select("#networkPlatformSelect");
  
  platforms.forEach(platform => {
    select.append("option")
      .attr("value", platform)
      .text(platform.charAt(0).toUpperCase() + platform.slice(1));
  });

  select.on("change", function() {
    renderNetworkGraph(this.value);
  });
}

function renderNetworkGraph(selectedPlatform) {
  if (!jsonData || jsonData.length === 0) return;

  const container = d3.select("#recVis");
  container.selectAll("*").remove();

  // Filter data by platform
  let filteredData = jsonData;
  if (selectedPlatform && selectedPlatform !== "all") {
    filteredData = jsonData.filter(d => d.platform === selectedPlatform);
  }

  if (filteredData.length === 0) {
    container.html("<p style='padding: 20px; color: #666;'>No data available for selected platform.</p>");
    return;
  }

  // Build graph: nodes are unique pages, edges are navigation relationships
  const pageMap = new Map(); // url -> node
  const edges = [];
  const platformGroups = {};

  filteredData.forEach(entry => {
    const url = entry.url || '';
    const platform = entry.platform || 'unknown';
    const category = entry.category || 'unknown';
    
    // Create or update node
    if (!pageMap.has(url)) {
      const nodeId = pageMap.size;
      const node = {
        id: nodeId,
        url: url,
        platform: platform,
        category: category,
        pageName: extractPageName(url),
        settingsCount: (entry.settings || []).length,
        image: entry.image || '',
        depth: getUrlDepth(url)
      };
      pageMap.set(url, node);
      
      if (!platformGroups[platform]) {
        platformGroups[platform] = [];
      }
      platformGroups[platform].push(node);
    } else {
      const node = pageMap.get(url);
      node.settingsCount += (entry.settings || []).length;
    }
  });

  const nodes = Array.from(pageMap.values());

  // Create edges based on URL hierarchy and relationships
  nodes.forEach((node, i) => {
    nodes.slice(i + 1).forEach(otherNode => {
      // Same platform
      if (node.platform === otherNode.platform) {
        const relationship = getUrlRelationship(node.url, otherNode.url);
        if (relationship) {
          edges.push({
            source: node.id,
            target: otherNode.id,
            type: relationship.type, // 'parent-child', 'sibling', 'same-base'
            strength: relationship.strength
          });
        }
      }
    });
  });

  if (nodes.length === 0) {
    container.html("<p style='padding: 20px; color: #666;'>No pages found for visualization.</p>");
    return;
  }

  // Set up SVG
  const margin = { top: 20, right: 20, bottom: 20, left: 20 };
  const width = 800 - margin.left - margin.right;
  const height = 500 - margin.top - margin.bottom;

  const svg = container.append("svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom)
    .style("background", "#fafafa")
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  // Color scale by platform
  const platforms = Array.from(new Set(nodes.map(n => n.platform)));
  const colorScale = d3.scaleOrdinal()
    .domain(platforms)
    .range(d3.schemeCategory10);

  // Create force simulation
  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id).distance(d => {
      // Adjust distance based on relationship type
      return d.type === 'parent-child' ? 100 : d.type === 'sibling' ? 150 : 200;
    }))
    .force("charge", d3.forceManyBody().strength(-300))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(d => Math.sqrt(d.settingsCount) * 5 + 20));

  // Create edges (links)
  const link = svg.append("g")
    .attr("class", "links")
    .selectAll("line")
    .data(edges)
    .enter().append("line")
    .attr("stroke", "#999")
    .attr("stroke-opacity", d => d.strength || 0.3)
    .attr("stroke-width", d => {
      if (d.type === 'parent-child') return 2;
      if (d.type === 'sibling') return 1.5;
      return 1;
    });

  // Create nodes
  const node = svg.append("g")
    .attr("class", "nodes")
    .selectAll("circle")
    .data(nodes)
    .enter().append("circle")
    .attr("r", d => Math.sqrt(d.settingsCount) * 3 + 8)
    .attr("fill", d => colorScale(d.platform))
    .attr("stroke", "#fff")
    .attr("stroke-width", 2)
    .call(drag(simulation));

  // Add labels
  const labels = svg.append("g")
    .attr("class", "labels")
    .selectAll("text")
    .data(nodes)
    .enter().append("text")
    .text(d => d.pageName)
    .style("font-size", "11px")
    .style("text-anchor", "middle")
    .style("pointer-events", "none")
    .attr("dy", d => Math.sqrt(d.settingsCount) * 3 + 15);

  // Add tooltips
  node.append("title")
    .text(d => `${d.pageName}\n${d.url}\nSettings: ${d.settingsCount}\nPlatform: ${d.platform}`);

  // Update positions on tick
  simulation.on("tick", () => {
    link
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    node
      .attr("cx", d => d.x)
      .attr("cy", d => d.y);

    labels
      .attr("x", d => d.x)
      .attr("y", d => d.y);
  });

  // Drag behavior
  function drag(simulation) {
    function dragstarted(event) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }

    function dragged(event) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }

    return d3.drag()
      .on("start", dragstarted)
      .on("drag", dragged)
      .on("end", dragended);
  }

  // Add legend
  const legend = svg.append("g")
    .attr("class", "legend")
    .attr("transform", `translate(10, 10)`);

  const legendItems = legend.selectAll(".legend-item")
    .data(platforms)
    .enter().append("g")
    .attr("class", "legend-item")
    .attr("transform", (d, i) => `translate(0, ${i * 20})`);

  legendItems.append("circle")
    .attr("r", 6)
    .attr("fill", colorScale);

  legendItems.append("text")
    .attr("x", 12)
    .attr("y", 5)
    .style("font-size", "12px")
    .text(d => d);

  // Summary
  container.append("div")
    .style("margin-top", "10px")
    .style("font-size", "12px")
    .style("color", "#666")
    .html(`<strong>Pages:</strong> ${nodes.length} | <strong>Connections:</strong> ${edges.length} | <strong>Platforms:</strong> ${platforms.length}`);
}

function extractPageName(url) {
  try {
    const urlObj = new URL(url);
    const path = urlObj.pathname;
    const parts = path.split('/').filter(p => p);
    const name = parts[parts.length - 1] || 'home';
    return name.replace(/_/g, ' ').replace(/-/g, ' ').replace(/[?&#].*/, '');
  } catch {
    return url.split('/').pop() || 'unknown';
  }
}

function getUrlDepth(url) {
  try {
    const urlObj = new URL(url);
    return urlObj.pathname.split('/').filter(p => p).length;
  } catch {
    return url.split('/').filter(p => p).length - 1;
  }
}

function getUrlRelationship(url1, url2) {
  try {
    const u1 = new URL(url1);
    const u2 = new URL(url2);
    
    // Must be same domain
    if (u1.hostname !== u2.hostname) return null;
    
    const path1 = u1.pathname.split('/').filter(p => p);
    const path2 = u2.pathname.split('/').filter(p => p);
    
    // Check for parent-child relationship
    const minLen = Math.min(path1.length, path2.length);
    let commonDepth = 0;
    for (let i = 0; i < minLen; i++) {
      if (path1[i] === path2[i]) {
        commonDepth++;
      } else {
        break;
      }
    }
    
    if (commonDepth > 0) {
      // Parent-child: one path extends the other
      if (path1.length === commonDepth && path2.length > commonDepth) {
        return { type: 'parent-child', strength: 0.6 };
      }
      if (path2.length === commonDepth && path1.length > commonDepth) {
        return { type: 'parent-child', strength: 0.6 };
      }
      
      // Siblings: same parent, different children
      if (path1.length === path2.length && path1.length === commonDepth + 1) {
        return { type: 'sibling', strength: 0.4 };
      }
      
      // Same base path, different query params
      if (commonDepth === path1.length && commonDepth === path2.length) {
        return { type: 'same-base', strength: 0.3 };
      }
    }
    
    // Same settings page base (e.g., both /settings/*)
    if (path1[0] === path2[0] && (path1[0] === 'settings' || path1[0] === 'profile')) {
      return { type: 'sibling', strength: 0.3 };
    }
    
    return null;
  } catch {
    // Fallback: simple string comparison
    if (url1.split('/').slice(0, 4).join('/') === url2.split('/').slice(0, 4).join('/')) {
      return { type: 'same-base', strength: 0.2 };
    }
    return null;
  }
}
