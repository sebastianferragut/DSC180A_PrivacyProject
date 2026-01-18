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

let allData = [];
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
 * Structure: Platform → Category → Setting (leaves)
 */
function buildHierarchy() {
  const filtered = getFilteredData();
  
  // Update weights based on current metric
  filtered.forEach(d => {
    d.weight = calculateWeight(d.stateType, d.category, currentSizingMetric);
  });
  
  // Group by platform
  const platformMap = new Map();
  
  filtered.forEach(d => {
    if (!platformMap.has(d.platform)) {
      platformMap.set(d.platform, new Map());
    }
    const categoryMap = platformMap.get(d.platform);
    
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
  
  platformMap.forEach((categoryMap, platform) => {
    const platformNode = {
      name: platform,
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
      
      // Calculate category value as sum of children
      categoryNode.value = d3.sum(categoryNode.children, d => d.value);
      platformNode.children.push(categoryNode);
    });
    
    // Calculate platform value as sum of children
    platformNode.value = d3.sum(platformNode.children, d => d.value);
    root.children.push(platformNode);
  });
  
  // Calculate root value
  root.value = d3.sum(root.children, d => d.value);
  
  // Use d3.hierarchy to create hierarchy structure
  currentRoot = d3.hierarchy(root)
    .sum(d => d.value || 0)
    .sort((a, b) => (b.value || 0) - (a.value || 0));
  
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
  if (typeof window.treemapHoverTimeout !== 'undefined' && window.treemapHoverTimeout) {
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
  
  // Color scale by category
  const categories = Array.from(new Set(allData.map(d => d.category)));

  const colorScale = d3.scaleOrdinal()
  .domain(categories)
  .range(d3.quantize(d3.interpolateRainbow, Math.max(categories.length, 3)));

  
  // Treemap layout
  const treemap = d3.treemap()
    .size([width, height])
    .padding(2)
    .round(true);
  
  treemap(currentRoot);
  
  // Draw cells
  const cells = g.selectAll("g")
    .data(currentRoot.descendants())
    .enter()
    .append("g")
    .attr("transform", d => `translate(${d.x0},${d.y0})`);
  
  cells.append("rect")
    .attr("class", "treemap-cell")
    .attr("width", d => d.x1 - d.x0)
    .attr("height", d => d.y1 - d.y0)
    .attr("fill", d => {
      if (d.depth === 0) return '#f0f0f0'; // Root
      
      // Determine if we're at root level or zoomed
      const atRoot = zoomStack.length === 0;
      
      if (atRoot) {
        if (d.depth === 1) return '#e0e0e0'; // Platform
        if (d.depth === 2) return colorScale(d.data.name); // Category
      } else {
        // Zoomed in - depth shifts
        if (d.depth === 0) return '#e0e0e0'; // Zoomed platform/category
        if (d.depth === 1) return colorScale(d.data.name); // Zoomed category/setting
      }
      
      // Leaf node: category color with state type overlay
      const category = d.data.category || (d.parent ? d.parent.data.name : 'unknown');
      const baseColor = colorScale(category);
      if (d.data.stateType === 'navigational') {
        return d3.color(baseColor).brighter(0.5);
      } else if (d.data.stateType === 'actionable') {
        return baseColor;
      } else {
        return d3.color(baseColor).darker(0.3);
      }
    })
    .attr("stroke", d => {
      if (d.data.stateType === 'navigational') return '#4CAF50';
      if (d.data.stateType === 'actionable') return '#2196F3';
      return '#fff';
    })
    .attr("stroke-width", d => {
      if (d.data.stateType) return 2;
      return 1.5;
    })
    .attr("stroke-dasharray", d => {
      if (d.data.stateType === 'navigational') return '4,2';
      return 'none';
    })
    .on("click", function(event, d) {
      event.stopPropagation();
      event.preventDefault();
      
      console.log("Cell clicked:", d.data.name, "depth:", d.depth, "children:", d.children ? d.children.length : 0);
      
      // Check if this is a leaf node (setting)
      const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
      
      if (!isLeaf && d.children && d.children.length > 0) {
        // Has children - zoom in
        console.log("Zooming into:", d.data.name);
        zoomInto(d);
      } else if (isLeaf) {
        // Leaf node - open URL
        console.log("Opening URL:", d.data.url);
        if (d.data.url) {
          window.open(d.data.url, '_blank');
        } else {
          console.warn("No URL found for setting:", d.data.name);
        }
      } else {
        console.log("No action for cell:", d.data.name);
      }
    })
    .style("cursor", d => {
      const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
      return (isLeaf && d.data.url) ? "pointer" : 
             (!isLeaf && d.children && d.children.length > 0) ? "pointer" : "default";
    });
  
  // Add labels (only if rectangle is large enough)
  cells.filter(d => {
    const width = d.x1 - d.x0;
    const height = d.y1 - d.y0;
    return width > 60 && height > 20;
  }).append("text")
    .attr("class", d => {
      const width = d.x1 - d.x0;
      const height = d.y1 - d.y0;
      return width < 100 || height < 30 ? "treemap-label treemap-label-small" : "treemap-label";
    })
    .attr("x", d => (d.x1 - d.x0) / 2)
    .attr("y", d => (d.y1 - d.y0) / 2)
    .attr("dy", "0.35em")
    .attr("fill", d => {
      // Ensure text is visible - use white on dark backgrounds, black on light
      const isRoot = d.depth === 0;
      const isPlatform = !zoomStack.length && d.depth === 1;
      
      if (isRoot || isPlatform) {
        // Light background - use dark text
        return "#333";
      }
      
      // For category and leaf nodes, check background color brightness
      // Categories are colored, so use white text with stroke for visibility
      return "#ffffff";
    })
    .attr("stroke", d => {
      // Add stroke to make text more visible on colored backgrounds
      const isRoot = d.depth === 0;
      const isPlatform = !zoomStack.length && d.depth === 1;
      
      if (isRoot || isPlatform) {
        return "none";
      }
      // White stroke on colored backgrounds for better visibility
      return "#000000";
    })
    .attr("stroke-width", d => {
      const isRoot = d.depth === 0;
      const isPlatform = !zoomStack.length && d.depth === 1;
      return (isRoot || isPlatform) ? 0 : "0.5px";
    })
    .attr("paint-order", "stroke")
    .style("font-weight", "600")
    .text(d => {
      const name = d.data.name || '';
      const width = d.x1 - d.x0;
      const height = d.y1 - d.y0;
      
      // Determine if this is a leaf (setting)
      const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
      
      if (isLeaf || (width > 100 && height > 30)) {
        // Truncate long names
        const maxChars = Math.floor(width / 6);
        if (name.length > maxChars) {
          return name.substring(0, maxChars - 3) + '...';
        }
      }
      
      return name;
    });
  
  // Tooltip - create a single tooltip instance
  const tooltip = d3.select("body").append("div")
    .attr("class", "treemap-tooltip")
    .style("opacity", 0)
    .style("pointer-events", "none") // Ensure tooltip doesn't interfere with mouse events
    .style("display", "none"); // Start hidden
  
  // Track current hovered element to prevent race conditions
  let hoverTimeout = null;
  
  cells.on("mouseover", function(event, d) {
    // Clear any pending timeout
    if (hoverTimeout) {
      clearTimeout(hoverTimeout);
      hoverTimeout = null;
    }
    
    // Stop any ongoing fade-out transition and show tooltip
    tooltip.interrupt();
    tooltip.style("display", "block");
    
    // Check if this is a leaf (setting) node
    const isLeaf = d.data.setting || (!d.children || d.children.length === 0);
    
    let content = '';
    if (isLeaf) {
      // Leaf node (setting)
      let platform = d.data.platform;
      let category = d.data.category;
      
      // Try to get from parent chain if not in data
      if (!platform && d.parent) {
        if (zoomStack.length === 0) {
          // At root: parent is category, parent.parent is platform
          platform = d.parent.parent ? d.parent.parent.data.name : 'unknown';
          category = d.parent.data.name;
        } else {
          // Zoomed in: need to trace back
          platform = zoomStack[0]?.root?.data?.name || 'unknown';
          category = currentRoot.data.name;
        }
      }
      
      content = `<strong>${d.data.setting || d.data.name}</strong>
         <p><strong>Platform:</strong> ${platform || 'unknown'}</p>
         <p><strong>Category:</strong> ${category || d.parent?.data?.name || 'unknown'}</p>
         <p><strong>State:</strong> ${d.data.state || 'N/A'}</p>
         <p><strong>Type:</strong> ${d.data.stateType || 'unknown'}</p>
         <p><strong>Description:</strong> ${truncate(d.data.description || '', 200)}</p>
         ${d.data.url ? `<p><strong>URL:</strong> ${d.data.url}</p>` : ''}`;
    } else {
      // Non-leaf node (platform or category)
      content = `<strong>${d.data.name}</strong>
         <p><strong>Value:</strong> ${d.value ? d.value.toFixed(2) : 0}</p>
         <p><strong>Children:</strong> ${d.children ? d.children.length : 0}</p>
         ${d.children && d.children.length > 0 ? '<p><em>Click to zoom in</em></p>' : ''}`;
    }
    
    tooltip.html(content)
      .style("left", (event.pageX + 10) + "px")
      .style("top", (event.pageY - 10) + "px")
      .transition()
      .duration(150)
      .style("opacity", 1);
  })
  .on("mousemove", function(event) {
    // Update position immediately without transition
    tooltip
      .style("left", (event.pageX + 10) + "px")
      .style("top", (event.pageY - 10) + "px");
  })
  .on("mouseout", function(event) {
    // Check if mouse is moving to another cell (event.relatedTarget should be another cell)
    const relatedTarget = event.relatedTarget;
    const isMovingToCell = relatedTarget && (
      relatedTarget.closest('g') || 
      relatedTarget.tagName === 'rect' || 
      relatedTarget.tagName === 'text'
    );
    
    // If moving to another cell, use small delay; otherwise hide immediately
    const delay = isMovingToCell ? 100 : 0;
    
    // Clear any existing timeout
    if (hoverTimeout) {
      clearTimeout(hoverTimeout);
    }
    
    hoverTimeout = setTimeout(() => {
      tooltip.transition()
        .duration(150)
        .style("opacity", 0)
        .on("end", function() {
          // Ensure tooltip is fully hidden
          tooltip.style("display", "none");
        });
      hoverTimeout = null;
    }, delay);
  });
  
  // Clean up tooltip when mouse leaves the SVG entirely
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
    .sum(d => d.value || 0)
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

