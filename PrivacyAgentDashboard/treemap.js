/**
 * Treemap Visualization for Privacy Settings
 * 
 * Expected CSV format:
 * - platform: string (e.g., "googleaccount", "facebook")
 * - url: string (full URL where setting was found)
 * - settings: string (Python dict list, e.g., "[{'setting': 'Name', 'description': '...', 'state': '...'}]")
 * - category: string (e.g., "data_collection_tracking", "security_authentication")
 * 
 * Hierarchy: Platform → Category → Setting (leaf nodes)
 */

// Header height for category labels
const CATEGORY_HEADER_HEIGHT = 32;

let allData = [];

// Category icons mapping (using Unicode symbols)
const categoryIcons = {
  'data_collection_tracking': '📊',
  'security_authentication': '🔒',
  'visibility_audience': '👁️',
  'identity_authentication': '🆔',
  'communication_messaging': '💬',
  'content_sharing': '📤',
  'location_privacy': '📍',
  'advertising_targeting': '📢',
  'default': '📁'
};
let currentRoot = null;
let zoomStack = [];
let currentSizingMetric = 'count';
let currentStateFilter = 'all';
let currentSearchQuery = '';

// Load and parse CSV
// Try local path first (if CSV is in same directory), then relative path
// Note: If opening HTML directly in browser (file://), you'll need a local server due to CORS
// Run: python -m http.server 8000 (from project root) then open http://localhost:8000/PrivacyAgentDashboard/old_index.html

const csvPaths = [
  "all_platforms_classified.csv",  // Local copy in dashboard directory
  "../database/data/all_platforms_classified.csv"  // Original location
];

function loadCSV(pathIndex = 0) {
  if (pathIndex >= csvPaths.length) {
    // All paths failed
    const container = d3.select("#treemapContainer");
    container.html(`
      <div style='padding: 20px; color: #d32f2f;'>
        <p><strong>Error loading data:</strong> Could not find CSV file</p>
        <p style='margin-top: 10px; font-size: 13px; color: #666;'>
          <strong>Solution:</strong> This visualization requires a web server due to browser security restrictions.<br>
          Run from the project root: <code>python -m http.server 8000</code><br>
          Then open: <code>http://localhost:8000/PrivacyAgentDashboard/old_index.html</code>
        </p>
        <p style='margin-top: 10px; font-size: 12px; color: #666;'>
          Tried paths:<br>
          ${csvPaths.map((p, i) => `${i + 1}. ${p}`).join('<br>')}
        </p>
      </div>
    `);
    return;
  }
  
  const csvPath = csvPaths[pathIndex];
  console.log(`Attempting to load CSV from: ${csvPath}`);
  
  d3.csv(csvPath).then(data => {
    console.log("CSV loaded successfully from:", csvPath);
    console.log("CSV rows:", data.length);
    if (!data || data.length === 0) {
      throw new Error("CSV file is empty");
    }
    allData = parseCSVData(data);
    console.log("Parsed data:", allData.length, "unique settings");
    buildHierarchy();
    renderTreemap();
  }).catch(err => {
    console.error(`Failed to load from ${csvPath}:`, err);
    // Try next path
    loadCSV(pathIndex + 1);
  });
}

// Start loading
loadCSV();

/**
 * Parse CSV data and extract settings
 * Handles Python dict format in settings column
 */
function parseCSVData(csvData) {
  const settingsMap = new Map(); // Deduplicate: platform + category + setting name
  
  csvData.forEach(row => {
    try {
      const platform = row.platform || 'unknown';
      const url = row.url || '';
      const category = row.category || 'unknown';
      
      // Parse settings field (Python dict string)
      let settings = [];
      try {
        // Replace single quotes with double quotes for JSON parsing
        const settingsStr = row.settings || '[]';
        const jsonStr = settingsStr.replace(/'/g, '"');
        settings = JSON.parse(jsonStr);
      } catch (e) {
        console.warn("Failed to parse settings for row:", row);
        return;
      }
      
      settings.forEach(setting => {
        const settingName = setting.setting || 'Unknown';
        const description = setting.description || '';
        const state = setting.state || 'unknown';
        
        // Create unique key for deduplication
        const key = `${platform}::${category}::${settingName}`;
        
        // Determine state_type
        const stateType = determineStateType(state);
        
        if (!settingsMap.has(key)) {
          settingsMap.set(key, {
            platform: platform,
            category: category,
            setting: settingName,
            description: description,
            state: state,
            stateType: stateType,
            url: url,
            weight: calculateWeight(stateType, category, currentSizingMetric)
          });
        } else {
          // Update URL if different (keep the first one found)
          const existing = settingsMap.get(key);
          if (!existing.url && url) {
            existing.url = url;
          }
        }
      });
    } catch (e) {
      console.warn("Error parsing row:", e, row);
    }
  });
  
  return Array.from(settingsMap.values());
}

/**
 * Determine state type from state value
 */
function determineStateType(state) {
  const stateLower = (state || '').toLowerCase();
  
  // Navigational indicators
  if (stateLower.includes('navigational') || 
      stateLower.includes('navigation') ||
      stateLower.includes('link') ||
      stateLower === 'navigational' ||
      stateLower === 'navigation link' ||
      stateLower === 'navigational link') {
    return 'navigational';
  }
  
  // Actionable indicators (On/Off, Enabled/Disabled, etc.)
  if (stateLower === 'on' || 
      stateLower === 'off' ||
      stateLower === 'enabled' ||
      stateLower === 'disabled' ||
      stateLower === 'paused' ||
      stateLower.includes('enabled') ||
      stateLower.includes('disabled') ||
      stateLower.match(/^(yes|no|true|false)$/i)) {
    return 'actionable';
  }
  
  // Unknown for everything else
  return 'unknown';
}

/**
 * Calculate weight based on sizing metric
 */
function calculateWeight(stateType, category, metric) {
  if (metric === 'count') {
    return 1;
  } else if (metric === 'actionable') {
    return stateType === 'actionable' ? 1 : 0.2;
  } else if (metric === 'risk-weighted') {
    const categoryLower = (category || '').toLowerCase();
    let riskWeight = 1;
    if (categoryLower.includes('tracking')) {
      riskWeight = 2;
    } else if (categoryLower.includes('security')) {
      riskWeight = 1.5;
    }
    return riskWeight;
  }
  return 1;
}

/**
 * Filter data based on current filters
 */
function getFilteredData() {
  let filtered = allData;
  
  // Apply state type filter
  if (currentStateFilter !== 'all') {
    filtered = filtered.filter(d => d.stateType === currentStateFilter);
  }
  
  // Apply search filter
  if (currentSearchQuery.trim()) {
    const query = currentSearchQuery.toLowerCase();
    filtered = filtered.filter(d => 
      d.setting.toLowerCase().includes(query) ||
      (d.description && d.description.toLowerCase().includes(query))
    );
  }
  
  return filtered;
}

/**
 * Build hierarchy from filtered data
 * Structure: Category → Setting (leaves) - no platform grouping
 */
function buildHierarchy() {
  const filtered = getFilteredData();
  
  // Update weights based on current metric
  filtered.forEach(d => {
    d.weight = calculateWeight(d.stateType, d.category, currentSizingMetric);
  });
  
  // Group directly by category (skip platform level)
  const categoryMap = new Map();
  
  filtered.forEach(d => {
    if (!categoryMap.has(d.category)) {
      categoryMap.set(d.category, []);
    }
    categoryMap.get(d.category).push(d);
  });
  
  // Build hierarchy object
  const root = {
    name: 'root',
    children: []
  };
  
  categoryMap.forEach((settings, category) => {
    const categoryNode = {
      name: category,
      children: settings.map(setting => ({
        name: setting.setting,
        setting: setting,
        value: setting.weight,
        url: setting.url,
        description: setting.description,
        state: setting.state,
        stateType: setting.stateType,
        platform: setting.platform,
        category: setting.category
      }))
    };
    
    root.children.push(categoryNode);
  });
  
  // Use d3.hierarchy to create hierarchy structure
  // Only leaf nodes contribute value (internal nodes get 0)
  currentRoot = d3.hierarchy(root)
    .sum(d => (d.children && d.children.length) ? 0 : (d.value || 0))
    .sort((a, b) => (b.value || 0) - (a.value || 0));
  
  // Debug: Check "communication notifications" category
  const commNotif = currentRoot.descendants().find(d => 
    d.data.name && d.data.name.toLowerCase().includes('communication')
  );
  if (commNotif) {
    console.log('Debug - Category:', commNotif.data.name, 
      'Children:', commNotif.children ? commNotif.children.length : 0,
      'Value:', commNotif.value);
  }
  
  return currentRoot;
}

/**
 * Render treemap visualization
 */
function renderTreemap() {
    if (!currentRoot) {
      buildHierarchy();
    }
  
    // Clean up any existing tooltips and clear hover timeouts
    d3.selectAll(".treemap-tooltip").remove();
    if (typeof window.treemapHoverTimeout !== "undefined" && window.treemapHoverTimeout) {
      clearTimeout(window.treemapHoverTimeout);
      window.treemapHoverTimeout = null;
    }
  
    const container = d3.select("#treemapContainer");
    container.selectAll("*").remove();
  
    const width = container.node().getBoundingClientRect().width || 1200;
    const height = 500;
  
    const svg = container.append("svg")
      .attr("width", width)
      .attr("height", height);
  
    const g = svg.append("g");
  
    // Root state for this render pass
    const atRootNow = zoomStack.length === 0;
  
    // Color scale by platform (not category)
    const platforms = Array.from(new Set(allData.map(d => d.platform))).sort();
    const categories = Array.from(new Set(allData.map(d => d.category)));
  
    const platformColorScale = d3.scaleOrdinal()
      .domain(platforms)
      .range(d3.quantize(d3.interpolateRainbow, Math.max(platforms.length, 3)));
  
    // Treemap layout
    const treemap = d3.treemap()
      .size([width, height])
      .paddingInner(2)
      .paddingOuter(2)
      .paddingTop(d => {
        const isCategory = (atRootNow && d.depth === 1) || (!atRootNow && d.depth === 0);
        return isCategory ? CATEGORY_HEADER_HEIGHT : 0;
      })
      .round(true);
  
    treemap(currentRoot);
  
    // Draw groups (one <g> per node)
    const cells = g.selectAll("g")
      .data(currentRoot.descendants())
      .enter()
      .append("g")
      .attr("transform", d => `translate(${d.x0},${d.y0})`);
  
    // ===============================
    // 1) Base rectangles FIRST
    // ===============================
    cells.append("rect")
      .attr("class", "treemap-cell")
      .attr("width", d => d.x1 - d.x0)
      .attr("height", d => d.y1 - d.y0)
      .attr("fill", d => {
        // Root container
        if (d.depth === 0) return "#f0f0f0";
  
        // Category nodes (light gray)
        const isCategory = (atRootNow && d.depth === 1) || (!atRootNow && d.depth === 0);
        if (isCategory) return "#e0e0e0";
  
        // Leaf nodes: color by platform and stateType
        const platform = d.data.platform || "unknown";
        const baseColor = platformColorScale(platform);
  
        if (d.data.stateType === "navigational") return d3.color(baseColor).brighter(0.5);
        if (d.data.stateType === "actionable") return baseColor;
        return d3.color(baseColor).darker(0.3);
      })
      .attr("stroke", d => {
        if (d.data.stateType === "navigational") return "#4CAF50";
        if (d.data.stateType === "actionable") return "#2196F3";
        return "#fff";
      })
      .attr("stroke-width", d => (d.data.stateType ? 2 : 1.5))
      .attr("stroke-dasharray", d => (d.data.stateType === "navigational" ? "4,2" : "none"))
      .on("click", function(event, d) {
        event.stopPropagation();
        event.preventDefault();
  
        const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
        if (!isLeaf && d.children && d.children.length > 0) {
          zoomInto(d);
        } else if (isLeaf && d.data.url) {
          window.open(d.data.url, "_blank");
        }
      })
      .style("cursor", d => {
        const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
        return (isLeaf && d.data.url)
          ? "pointer"
          : (!isLeaf && d.children && d.children.length > 0)
            ? "pointer"
            : "default";
      });
  
    // ===============================
    // 2) Category headers AFTER rects
    // ===============================
    const categoryCells = cells.filter(d => {
      const isCategory = (atRootNow && d.depth === 1) || (!atRootNow && d.depth === 0);
      return isCategory && d.children && d.children.length > 0;
    });
  
    categoryCells.each(function(d) {
      const categoryGroup = d3.select(this);
  
      // Click overlay (so clicking header area also zooms)
      categoryGroup.append("rect")
        .attr("class", "category-click-overlay")
        .attr("x", 0)
        .attr("y", 0)
        .attr("width", d.x1 - d.x0)
        .attr("height", d.y1 - d.y0)
        .attr("fill", "transparent")
        .style("cursor", "pointer")
        .style("pointer-events", "all")
        .on("click", function(event) {
          event.stopPropagation();
          event.preventDefault();
          zoomInto(d);
        })
        .on("mouseover", function() {
          d3.select(this).attr("fill", "rgba(0,0,0,0.05)");
        })
        .on("mouseout", function() {
          d3.select(this).attr("fill", "transparent");
        });
  
      // Header bar
      categoryGroup.append("rect")
        .attr("class", "category-header-bg")
        .attr("x", 0)
        .attr("y", 0)
        .attr("width", d.x1 - d.x0)
        .attr("height", CATEGORY_HEADER_HEIGHT)
        .attr("fill", "#d4d4d4")
        .attr("stroke", "#999")
        .attr("stroke-width", 1)
        .style("pointer-events", "none");
  
      // Icon + label
      const categoryKey = (d.data.name || "").toLowerCase();
      const icon = categoryIcons[categoryKey] || categoryIcons.default;
  
      categoryGroup.append("text")
        .attr("class", "category-header-icon")
        .attr("x", 8)
        .attr("y", CATEGORY_HEADER_HEIGHT / 2)
        .attr("dy", "0.35em")
        .attr("font-size", "18px")
        .style("pointer-events", "none")
        .text(icon);
  
      categoryGroup.append("text")
        .attr("class", "category-header-label")
        .attr("x", 32)
        .attr("y", CATEGORY_HEADER_HEIGHT / 2)
        .attr("dy", "0.35em")
        .attr("fill", "#333")
        .style("font-size", "14px")
        .style("font-weight", "600")
        .style("pointer-events", "none")
        .text((d.data.name || "").replace(/_/g, " "));
  
      // Ensure header stays on top within this group
      categoryGroup
        .selectAll(".category-header-bg, .category-header-icon, .category-header-label")
        .raise();
    });
  
    // ===============================
    // 3) Leaf labels (exclude categories)
    // ===============================
    cells.filter(d => {
      const isCategory = (atRootNow && d.depth === 1) || (!atRootNow && d.depth === 0);
      const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
      const w = d.x1 - d.x0;
      const h = d.y1 - d.y0;
      return !isCategory && isLeaf && w > 60 && h > 20;
    }).append("text")
      .attr("class", d => {
        const w = d.x1 - d.x0;
        const h = d.y1 - d.y0;
        return w < 100 || h < 30 ? "treemap-label treemap-label-small" : "treemap-label";
      })
      .attr("x", d => (d.x1 - d.x0) / 2)
      .attr("y", d => (d.y1 - d.y0) / 2)
      .attr("dy", "0.35em")
      .attr("fill", d => {
        // Root / category = dark text, leaves = white
        const isRoot = d.depth === 0;
        const isCategory = (atRootNow && d.depth === 1) || (!atRootNow && d.depth === 0);
        if (isRoot || isCategory) return "#333";
        return "#ffffff";
      })
      .attr("stroke", d => {
        const isRoot = d.depth === 0;
        const isCategory = (atRootNow && d.depth === 1) || (!atRootNow && d.depth === 0);
        if (isRoot || isCategory) return "none";
        return "#000000";
      })
      .attr("stroke-width", d => {
        const isRoot = d.depth === 0;
        const isCategory = (atRootNow && d.depth === 1) || (!atRootNow && d.depth === 0);
        return (isRoot || isCategory) ? 0 : "0.5px";
      })
      .attr("paint-order", "stroke")
      .style("font-weight", "600")
      .text(d => {
        const name = d.data.name || "";
        const w = d.x1 - d.x0;
        const maxChars = Math.floor(w / 6);
        if (name.length > maxChars && maxChars > 3) {
          return name.substring(0, maxChars - 3) + "...";
        }
        return name;
      });
  
    // ===============================
    // Tooltip - single instance
    // ===============================
    const tooltip = d3.select("body").append("div")
      .attr("class", "treemap-tooltip")
      .style("opacity", 0)
      .style("pointer-events", "none")
      .style("display", "none");
  
    let hoverTimeout = null;
  
    cells.on("mouseover", function(event, d) {
      if (hoverTimeout) {
        clearTimeout(hoverTimeout);
        hoverTimeout = null;
      }
  
      tooltip.interrupt();
      tooltip.style("display", "block");
  
      const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
  
      let content = "";
      if (isLeaf) {
        let platform = d.data.platform;
        let category = d.data.category;
  
        if (!platform && d.parent) {
          category = d.parent.data.name;
          platform = d.data.platform || "unknown";
        }
  
        content = `<strong>${d.data.setting || d.data.name}</strong>
          <p><strong>Platform:</strong> ${platform || "unknown"}</p>
          <p><strong>Category:</strong> ${category || d.parent?.data?.name || "unknown"}</p>
          <p><strong>State:</strong> ${d.data.state || "N/A"}</p>
          <p><strong>Type:</strong> ${d.data.stateType || "unknown"}</p>
          <p><strong>Description:</strong> ${truncate(d.data.description || "", 200)}</p>
          ${d.data.url ? `<p><strong>URL:</strong> ${d.data.url}</p>` : ""}`;
      } else {
        content = `<strong>${d.data.name}</strong>
          <p><strong>Value:</strong> ${d.value ? d.value.toFixed(2) : 0}</p>
          <p><strong>Children:</strong> ${d.children ? d.children.length : 0}</p>
          ${d.children && d.children.length > 0 ? "<p><em>Click to zoom in</em></p>" : ""}`;
      }
  
      tooltip.html(content)
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px")
        .transition()
        .duration(150)
        .style("opacity", 1);
    })
    .on("mousemove", function(event) {
      tooltip
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px");
    })
    .on("mouseout", function(event) {
      const relatedTarget = event.relatedTarget;
      const isMovingToCell = relatedTarget && (
        relatedTarget.closest("g") ||
        relatedTarget.tagName === "rect" ||
        relatedTarget.tagName === "text"
      );
  
      const delay = isMovingToCell ? 100 : 0;
  
      if (hoverTimeout) clearTimeout(hoverTimeout);
  
      hoverTimeout = setTimeout(() => {
        tooltip.transition()
          .duration(150)
          .style("opacity", 0)
          .on("end", function() {
            tooltip.style("display", "none");
          });
        hoverTimeout = null;
      }, delay);
    });
  
    svg.on("mouseleave", function() {
      if (hoverTimeout) {
        clearTimeout(hoverTimeout);
        hoverTimeout = null;
      }
      tooltip.interrupt();
      tooltip.transition()
        .duration(150)
        .style("opacity", 0)
        .on("end", function() {
          tooltip.style("display", "none");
        });
    });
  
    updateBreadcrumbs();
    renderLegend(platforms, platformColorScale, categories);
  }
  

/**
 * Render legend showing platforms (with colors) and categories
 */
function renderLegend(platforms, platformColorScale, categories) {
  const legendContainer = d3.select("#treemapLegend");
  legendContainer.selectAll("*").remove();
  
  // Create legend wrapper
  const legend = legendContainer.append("div")
    .attr("class", "legend-wrapper")
    .style("display", "flex")
    .style("gap", "30px")
    .style("margin-top", "15px")
    .style("padding", "15px")
    .style("background", "#f9f9f9")
    .style("border-radius", "6px")
    .style("border", "1px solid #e0e0e0");
  
  // Platforms section (with colors)
  const platformsSection = legend.append("div")
    .attr("class", "legend-section platforms-section");
  
  platformsSection.append("div")
    .attr("class", "legend-title")
    .style("font-weight", "600")
    .style("margin-bottom", "8px")
    .style("font-size", "14px")
    .style("color", "#333")
    .text("Platforms (colors)");
  
  const platformsList = platformsSection.append("div")
    .attr("class", "legend-items")
    .style("display", "flex")
    .style("flex-wrap", "wrap")
    .style("gap", "12px");
  
  platforms.forEach(platform => {
    const item = platformsList.append("div")
      .attr("class", "legend-item")
      .style("display", "flex")
      .style("align-items", "center")
      .style("gap", "6px")
      .style("font-size", "12px");
    
    item.append("div")
      .attr("class", "legend-color")
      .style("width", "16px")
      .style("height", "16px")
      .style("background", platformColorScale(platform))
      .style("border", "1px solid #ccc")
      .style("border-radius", "3px")
      .style("flex-shrink", "0");
    
    item.append("span")
      .text(platform.charAt(0).toUpperCase() + platform.slice(1));
  });
  
  // Categories section (grouping info, no colors)
  const categoriesSection = legend.append("div")
    .attr("class", "legend-section categories-section");
  
  categoriesSection.append("div")
    .attr("class", "legend-title")
    .style("font-weight", "600")
    .style("margin-bottom", "8px")
    .style("font-size", "14px")
    .style("color", "#333")
    .text("Categories (grouping)");
  
  const categoriesList = categoriesSection.append("div")
    .attr("class", "legend-items")
    .style("display", "flex")
    .style("flex-wrap", "wrap")
    .style("gap", "8px");
  
  categories.forEach(category => {
    categoriesList.append("div")
      .attr("class", "legend-platform-item")
      .style("padding", "4px 10px")
      .style("background", "#fff")
      .style("border", "1px solid #ddd")
      .style("border-radius", "4px")
      .style("font-size", "12px")
      .style("color", "#666")
      .text(category.replace(/_/g, ' '));
  });
}

/**
 * Zoom into a node
 */
function zoomInto(d) {
  if (d.depth === 0) {
    // Already at root
    return;
  }
  
  // Save current root to stack (clone it)
  if (currentRoot) {
    zoomStack.push({
      root: currentRoot,
      name: d.data.name
    });
  }
  
  // Create new root from selected node's children
  const newRoot = {
    name: d.data.name,
    children: d.children ? d.children.map(child => ({
      name: child.data.name,
      children: child.children || [],
      value: child.value,
      setting: child.data.setting,
      url: child.data.url,
      description: child.data.description,
      state: child.data.state,
      stateType: child.data.stateType,
      platform: child.data.platform,
      category: child.data.category
    })) : [],
    value: d.value
  };
  
  currentRoot = d3.hierarchy(newRoot)
    .sum(d => (d.children && d.children.length) ? 0 : (d.value || 0))
    .sort((a, b) => (b.value || 0) - (a.value || 0));
  
  renderTreemap();
}

/**
 * Zoom out one level
 */
function zoomOut() {
  if (zoomStack.length > 0) {
    const saved = zoomStack.pop();
    currentRoot = saved.root;
    renderTreemap();
  } else {
    // Reset to root
    currentRoot = null;
    zoomStack = [];
    buildHierarchy();
    renderTreemap();
  }
}

/**
 * Update breadcrumbs
 */
function updateBreadcrumbs() {
  const breadcrumbs = d3.select("#breadcrumbs");
  breadcrumbs.selectAll("*").remove();
  
  if (zoomStack.length === 0) {
    breadcrumbs.append("span")
      .attr("class", "breadcrumb-item active")
      .text("All");
    return;
  }
  
  // Add root
  breadcrumbs.append("span")
    .attr("class", "breadcrumb-item")
    .text("All")
    .on("click", function() {
      currentRoot = null;
      zoomStack = [];
      buildHierarchy();
      renderTreemap();
    });
  
  // Build path from zoom stack and current root
  const path = [];
  zoomStack.forEach(saved => {
    if (saved.name && saved.name !== 'root') {
      path.push(saved.name);
    }
  });
  if (currentRoot && currentRoot.data.name && currentRoot.data.name !== 'root') {
    path.push(currentRoot.data.name);
  }
  
  path.forEach((name, i) => {
    breadcrumbs.append("span")
      .attr("class", "breadcrumb-separator")
      .text(" > ");
    
    const isLast = i === path.length - 1;
    breadcrumbs.append("span")
      .attr("class", `breadcrumb-item ${isLast ? 'active' : ''}`)
      .text(name)
      .on("click", function() {
        if (!isLast) {
          // Zoom out to this level
          const levelsToPop = path.length - i - 1;
          for (let j = 0; j < levelsToPop; j++) {
            if (zoomStack.length > 0) {
              currentRoot = zoomStack.pop();
            }
          }
          renderTreemap();
        }
      });
  });
}

/**
 * Truncate text
 */
function truncate(text, maxLength) {
  if (!text) return '';
  return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
}

/**
 * Setup event handlers - called after DOM is ready
 */
function setupEventHandlers() {
  const sizingMetricSelect = document.getElementById("sizingMetric");
  const stateTypeFilterSelect = document.getElementById("stateTypeFilter");
  const searchBox = document.getElementById("searchBox");
  const resetViewBtn = document.getElementById("resetView");
  
  if (sizingMetricSelect) {
    sizingMetricSelect.addEventListener("change", function() {
      currentSizingMetric = this.value;
      buildHierarchy();
      renderTreemap();
    });
  } else {
    console.warn("sizingMetric element not found");
  }
  
  if (stateTypeFilterSelect) {
    stateTypeFilterSelect.addEventListener("change", function() {
      currentStateFilter = this.value;
      buildHierarchy();
      renderTreemap();
    });
  } else {
    console.warn("stateTypeFilter element not found");
  }
  
  if (searchBox) {
    searchBox.addEventListener("input", function() {
      currentSearchQuery = this.value;
      buildHierarchy();
      renderTreemap();
    });
  } else {
    console.warn("searchBox element not found");
  }
  
  if (resetViewBtn) {
    resetViewBtn.addEventListener("click", function() {
      currentRoot = null;
      zoomStack = [];
      currentSearchQuery = '';
      if (searchBox) {
        searchBox.value = "";
      }
      buildHierarchy();
      renderTreemap();
    });
  } else {
    console.warn("resetView element not found");
  }
  
  // Handle window resize
  window.addEventListener("resize", function() {
    if (currentRoot) {
      renderTreemap();
    }
  });
}

// Setup event handlers when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupEventHandlers);
} else {
  // DOM is already ready
  setupEventHandlers();
}

