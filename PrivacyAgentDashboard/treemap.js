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

const PLATFORM_COLORS = {
    facebook: "#1877F2",
    googleaccount: "#34A853",
    instagram: "#E4405F",
    linkedin: "#0A66C2",
    reddit: "#FF4500",
    zoom: "#2D8CFF",
    spotify: "#1DB954",
    twitterx: "#111111",
    unknown: "#9E9E9E"
  };
  

let currentRoot = null;
let zoomStack = [];
let currentSizingMetric = 'count';
let currentStateFilter = 'all';
let currentSearchQuery = '';
let currentPlatformFilter = ['all']; // Array to support multiple selections

// Detail view state
let isDetailView = false;
let detailPayload = null;
let detailBreadcrumb = null;
let detailNode = null;

// DOM references for setting details panel
let settingDetails, detailsTitle, detailsSubtitle, detailsDescription, detailsState, 
    detailsActionable, detailsRisk, detailsOpenUrl, detailsClose;

// Area evidence panel state
let areaEvidenceEl = null;

// Load and parse CSV
// Try local path first (if CSV is in same directory), then relative path
// Note: If opening HTML directly in browser (file://), you'll need a local server due to CORS
// Run: python -m http.server 8000 (from project root) then open http://localhost:8000/PrivacyAgentDashboard/old_index.html

const csvPaths = [
  "all_platforms_classified_with_clicks.csv",  // File with clicks data (if in explore directory)
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
    populatePlatformFilter();
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
    const platform = (row.platform || "unknown").trim().toLowerCase();

      const url = row.url || '';
      const category = row.category || 'unknown';
      
    // Parse settings field (Python dict string) - robust conversion
    let settings = [];
    try {
    const settingsStr = row.settings || "[]";
    settings = parsePythonDictList(settingsStr);
    } catch (e) {
      console.warn("Failed to parse settings for row:", e, row);
      return;
    }

      
      settings.forEach(setting => {
        const settingName = setting.setting || 'Unknown';
        const description = setting.description || '';
        const state = setting.state || 'unknown';
        const clicks = setting.clicks ? parseInt(setting.clicks, 10) : 0; // Extract clicks, default to 0
        
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
            clicks: clicks, // Store clicks value
            weight: calculateWeight(stateType, category, currentSizingMetric, clicks)
          });
        } else {
          // Update URL if different (keep the first one found)
          const existing = settingsMap.get(key);
          if (!existing.url && url) {
            existing.url = url;
          }
          // Update clicks if available (use max or latest)
          if (clicks > 0) {
            existing.clicks = Math.max(existing.clicks || 0, clicks);
          }
        }
      });
    } catch (e) {
      console.warn("Error parsing row:", e, row);
    }
  });
  
  return Array.from(settingsMap.values());
}

function parsePythonDictList(pyStr) {
    if (!pyStr || pyStr.trim() === "") return [];
  
    let s = pyStr.trim();
  
    // 1) Fix doubled quotes from CSV export: ""text"" -> "text"
    s = s.replace(/""/g, '"');
  
    // 2) Python literals -> JSON
    s = s.replace(/\bNone\b/g, "null")
         .replace(/\bTrue\b/g, "true")
         .replace(/\bFalse\b/g, "false");
  
    // 3) Convert keys: 'key': -> "key":
    s = s.replace(/'([A-Za-z0-9_]+)'\s*:/g, '"$1":');
  
    // 4) Convert single-quoted values: : 'value' -> : "value"
    s = s.replace(/:\s*'((?:\\'|[^'])*)'/g, (match, val) => {
      const cleaned = val.replace(/\\'/g, "'").replace(/"/g, '\\"');
      return `: "${cleaned}"`;
    });
  
    // 5) Convert double-quoted values left over from your data:
    //    : "value" is already JSON-valid, BUT your strings are currently unescaped
    //    because they came from Python-ish text. We just ensure internal quotes are escaped.
    //    (After step 1, "" -> ", so these are normal JSON strings already.)
    //    Nothing to do here unless there are stray newlines.
    s = s.replace(/\n/g, "\\n");
  
    // 6) Parse
    return JSON.parse(s);
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
function calculateWeight(stateType, category, metric, clicks = 0) {
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
  } else if (metric === 'clicks') {
    // Use clicks value, default to 1 if clicks is 0 or missing
    return clicks > 0 ? clicks : 1;
  }
  return 1;
}

/**
 * Filter data based on current filters
 */
function getFilteredData() {
  let filtered = allData;
  
  // Apply platform filter (supports multiple selections)
  if (!currentPlatformFilter.includes('all') && currentPlatformFilter.length > 0) {
    filtered = filtered.filter(d => currentPlatformFilter.includes(d.platform));
  }
  
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
    d.weight = calculateWeight(d.stateType, d.category, currentSizingMetric, d.clicks || 0);
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
        meta: setting,
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
 * Get breadcrumb path for a node (Platform → Category → Setting)
 */
function getBreadcrumb(d) {
  if (!d) return "";
  
  const parts = [];
  let node = d;
  
  // Traverse up the hierarchy to collect parts
  while (node && node.data) {
    if (node.data.name && node.data.name !== 'root') {
      // For leaf nodes, use the setting name; for categories, use category name
      if (!node.children || node.children.length === 0) {
        // Leaf node - use setting name
        const settingName = node.data.setting || node.data.name || "Setting";
        parts.unshift(settingName);
      } else {
        // Category node
        const categoryName = node.data.name.replace(/_/g, ' ');
        parts.unshift(categoryName);
      }
    }
    node = node.parent;
  }
  
  // Add platform if available from leaf data
  if (d.data && d.data.platform) {
    const platformName = d.data.platform.charAt(0).toUpperCase() + d.data.platform.slice(1);
    parts.unshift(platformName);
  }
  
  return parts.join(" → ") || "Setting";
}

/**
 * Extract setting payload from node data with fallbacks
 */
function getSettingPayload(d) {
  if (!d || !d.data) {
    return {
      name: "Setting",
      description: "",
      state: "",
      url: "",
      actionable: "",
      risk: "",
      platform: "",
      category: ""
    };
  }
  
  // Handle nested data structures
  let data = d.data;
  if (data.meta) {
    data = { ...data, ...data.meta };
  }
  if (data.settingObj) {
    data = { ...data, ...data.settingObj };
  }
  if (Array.isArray(data.settings) && data.settings.length > 0) {
    data = { ...data, ...data.settings[0] };
  }
  
  // Extract fields with fallbacks
  const stateType = (data.stateType || "").toLowerCase();
  const isActionable = stateType === "actionable" || stateType === "navigational";
  
  // Risk calculation (same as calculateWeight for risk-weighted)
  const categoryLower = (data.category || "").toLowerCase();
  let riskLevel = "Standard";
  if (categoryLower.includes('tracking')) {
    riskLevel = "High";
  } else if (categoryLower.includes('security')) {
    riskLevel = "Medium";
  }
  
  return {
    name: data.setting || data.name || "Setting",
    description: data.description || "",
    state: data.state || "",
    url: data.url || data.link || "",
    actionable: isActionable ? (stateType === "actionable" ? "Actionable" : "Navigational") : "Unknown",
    risk: data.risk || data.risk_level || data.risk_weight || riskLevel,
    platform: data.platform || "",
    category: data.category || "",
    clicks: data.clicks || 0
  };
}

/**
 * Open the details panel
 */
function openDetails() {
  if (settingDetails) {
    settingDetails.classList.remove("hidden");
  }
}

/**
 * Close the details panel
 */
function closeDetails() {
  if (settingDetails) {
    settingDetails.classList.add("hidden");
  }
}

/**
 * Show setting details in the panel
 */
function showSettingDetails(d) {
  if (!d) return;
  
  const payload = getSettingPayload(d);
  const breadcrumb = getBreadcrumb(d);
  
  // Update panel fields with null checks
  if (detailsTitle) {
    detailsTitle.textContent = payload.name;
  }
  if (detailsSubtitle) {
    detailsSubtitle.textContent = breadcrumb;
  }
  if (detailsDescription) {
    detailsDescription.textContent = payload.description || "No description available.";
  }
  if (detailsState) {
    detailsState.textContent = payload.state || "N/A";
  }
  if (detailsActionable) {
    detailsActionable.textContent = payload.actionable || "Unknown";
  }
  if (detailsRisk) {
    detailsRisk.textContent = payload.risk || "Standard";
  }
  if (detailsOpenUrl) {
    if (payload.url) {
      detailsOpenUrl.href = payload.url;
      detailsOpenUrl.style.pointerEvents = "auto";
      detailsOpenUrl.style.opacity = "1";
      detailsOpenUrl.style.cursor = "pointer";
    } else {
      detailsOpenUrl.href = "#";
      detailsOpenUrl.style.pointerEvents = "none";
      detailsOpenUrl.style.opacity = "0.5";
      detailsOpenUrl.style.cursor = "not-allowed";
    }
  }
  
  openDetails();
}

/**
 * Attach a simple name-only tooltip to a button element
 * Shows ONLY the button label (aria-label or textContent)
 */
function attachButtonNameTooltip(buttonEl) {
  if (!buttonEl || buttonEl.__hasNameTooltip) return;
  buttonEl.__hasNameTooltip = true;

  let tip = document.querySelector(".button-name-tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "button-name-tooltip";
    document.body.appendChild(tip);
  }

  function getLabel() {
    return (buttonEl.getAttribute("aria-label") || buttonEl.textContent || "").trim();
  }

  buttonEl.addEventListener("mouseenter", (e) => {
    const label = getLabel();
    if (!label) return;
    tip.textContent = label; // ONLY the name
    tip.style.opacity = "1";
    tip.style.left = (e.pageX + 10) + "px";
    tip.style.top = (e.pageY - 10) + "px";
  });

  buttonEl.addEventListener("mousemove", (e) => {
    tip.style.left = (e.pageX + 10) + "px";
    tip.style.top = (e.pageY - 10) + "px";
  });

  buttonEl.addEventListener("mouseleave", () => {
    tip.style.opacity = "0";
  });
}

/**
 * Create a simple tooltip for SVG button groups (like detail buttons)
 * Shows ONLY the button label text
 */
function createSVGButtonTooltip(buttonGroup, label) {
  let tip = null;
  
  buttonGroup
    .on("mouseenter", function(event) {
      if (!tip) {
        tip = d3.select("body").append("div")
          .attr("class", "button-name-tooltip")
          .style("opacity", 0)
          .style("position", "absolute")
          .style("background", "rgba(0, 0, 0, 0.85)")
          .style("color", "white")
          .style("padding", "6px 10px")
          .style("border-radius", "4px")
          .style("font-size", "12px")
          .style("pointer-events", "none")
          .style("z-index", "10000")
          .style("white-space", "nowrap");
      }
      tip
        .text(label) // ONLY the name
        .style("opacity", 1)
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px");
    })
    .on("mousemove", function(event) {
      if (tip) {
        tip
          .style("left", (event.pageX + 10) + "px")
          .style("top", (event.pageY - 10) + "px");
      }
    })
    .on("mouseout", function() {
      if (tip) {
        tip.style("opacity", 0);
      }
    });
}

/**
 * Ensure area evidence panel exists and return it
 */
function ensureAreaEvidencePanel() {
  if (!areaEvidenceEl) {
    const container = document.getElementById("treemapContainer");
    if (!container) return null;
    
    // Ensure container is position relative
    if (window.getComputedStyle(container).position === "static") {
      container.style.position = "relative";
    }
    
    areaEvidenceEl = document.createElement("div");
    areaEvidenceEl.className = "area-evidence hidden";
    container.appendChild(areaEvidenceEl);
  }
  return areaEvidenceEl;
}

/**
 * Wire evidence panel hover behavior to reset when leaving actions area (when not over treemap)
 * Only the actions area (buttons/links) is a safe hover zone, not the panel body
 */
function wireEvidencePanelHoverBehavior() {
  const panel = ensureAreaEvidencePanel();
  if (!panel) return;
  
  // Only wire once
  if (panel.__wired) return;
  panel.__wired = true;
  
  let restoreGuard = false; // Guard to avoid flicker
  
  panel.addEventListener("mouseleave", function(event) {
    const relatedTarget = event.relatedTarget;
    // Check if mouse is moving to actions area or treemap element
    const isMovingToActions = relatedTarget && relatedTarget.closest && relatedTarget.closest(".area-evidence-actions");
    const hoveredCell = document.querySelector("rect.treemap-cell:hover, rect.category-click-overlay:hover");
    const isMovingToTreemap = hoveredCell !== null;
    
    if (!isMovingToActions && !isMovingToTreemap && !restoreGuard) {
      // Not moving to safe zones, safe to reset
      restoreGuard = true;
      setTimeout(() => {
        hideAreaEvidence();
        
        // Reset visual state
        const container = d3.select("#treemapContainer");
        const svg = container.select("svg");
        if (!svg.empty()) {
          const g = svg.select("g");
          g.selectAll("rect.treemap-cell").style("opacity", 1);
          g.selectAll("text.treemap-label").style("opacity", 1);
        }
        restoreGuard = false;
      }, 50);
    }
  });
}

/**
 * Show area evidence panel
 */
function showAreaEvidence(title, htmlBody) {
  const panel = ensureAreaEvidencePanel();
  if (!panel) return;
  
  panel.innerHTML = `
    <div class="area-evidence-title">${title}</div>
    <div class="area-evidence-body">${htmlBody}</div>
    <div class="area-evidence-actions">
      <!-- Actions/buttons area - safe hover zone -->
    </div>
  `;
  panel.classList.remove("hidden");
  
  // Wire hover behavior when panel is shown
  wireEvidencePanelHoverBehavior();
  
  // Wire body hover behavior after DOM is ready
  setTimeout(function() {
    const bodyEl = panel.querySelector(".area-evidence-body");
    if (bodyEl && !bodyEl.__wired) {
      bodyEl.__wired = true;
      let restoreGuard = false;
      bodyEl.addEventListener("mouseenter", function() {
        // Check if mouse is over treemap element to avoid flicker
        const hoveredCell = document.querySelector("rect.treemap-cell:hover, rect.category-click-overlay:hover");
        if (!hoveredCell && !restoreGuard) {
          restoreGuard = true;
          setTimeout(() => {
            hideAreaEvidence();
            
            // Reset visual state
            const container = d3.select("#treemapContainer");
            const svg = container.select("svg");
            if (!svg.empty()) {
              const g = svg.select("g");
              g.selectAll("rect.treemap-cell").style("opacity", 1);
              g.selectAll("text.treemap-label").style("opacity", 1);
            }
            restoreGuard = false;
          }, 100);
        }
      });
    }
  }, 10);
}

/**
 * Hide area evidence panel
 */
function hideAreaEvidence() {
  if (areaEvidenceEl) {
    areaEvidenceEl.classList.add("hidden");
  }
}

/**
 * Calculate pixel area for a leaf node
 */
function leafPixelArea(leaf) {
  if (!leaf || leaf.x1 === undefined || leaf.x0 === undefined || 
      leaf.y1 === undefined || leaf.y0 === undefined) {
    return 0;
  }
  const w = Math.max(0, leaf.x1 - leaf.x0);
  const h = Math.max(0, leaf.y1 - leaf.y0);
  return w * h;
}

/**
 * Format integer with locale string
 */
function fmtInt(n) {
  return (n || 0).toLocaleString();
}

/**
 * Enter detail view for a leaf node
 */
function enterDetailView(d) {
  isDetailView = true;
  detailNode = d;
  detailPayload = getSettingPayload(d);
  detailBreadcrumb = getBreadcrumb(d);
  renderTreemap();
}

/**
 * Exit detail view and return to treemap
 */
function exitDetailView() {
  isDetailView = false;
  detailNode = null;
  detailPayload = null;
  detailBreadcrumb = null;
  renderTreemap();
}

/**
 * Wrap text to fit within max width and optionally max height
 */
function wrapText(textElement, text, maxWidth, maxHeight = null) {
  const words = text.split(/\s+/).reverse();
  let word;
  let line = [];
  let lineNumber = 0;
  const lineHeight = 1.2;
  const fontSize = parseFloat(textElement.attr("font-size") || "13");
  const lineHeightPx = fontSize * lineHeight;
  const y = textElement.attr("y");
  const dy = parseFloat(textElement.attr("dy") || 0);
  let tspan = textElement.text(null)
    .append("tspan")
    .attr("x", textElement.attr("x") || 0)
    .attr("y", y)
    .attr("dy", dy + "em");
  
  while (word = words.pop()) {
    line.push(word);
    tspan.text(line.join(" "));
    if (tspan.node().getComputedTextLength() > maxWidth && line.length > 1) {
      line.pop();
      tspan.text(line.join(" "));
      line = [word];
      lineNumber++;
      
      // Check max height if provided
      if (maxHeight !== null && (lineNumber * lineHeightPx) > maxHeight) {
        // Truncate and add ellipsis
        const currentText = tspan.text();
        tspan.text(currentText.substring(0, currentText.length - 3) + "...");
        break;
      }
      
      tspan = textElement.append("tspan")
        .attr("x", textElement.attr("x") || 0)
        .attr("y", y)
        .attr("dy", lineNumber * lineHeight + dy + "em")
        .text(word);
    }
  }
}

/**
 * Render detail view card in SVG
 */
function renderDetailView(svg, width, height, payload, breadcrumb, focusNode) {
  const padding = 14;
  const cornerRadius = 8;
  const headerHeight = 62; // Title + subtitle + spacing
  const footerHeight = 56; // Buttons + spacing
  
  // Calculate card dimensions - make it smaller and more compact
  const cardWidth = Math.min(420, width * 0.60);
  // Ensure card height leaves room for buttons at the bottom
  const maxCardHeight = Math.min(380, height * 0.55);
  const cardHeight = maxCardHeight;
  
  const focusCx = focusNode
    ? (focusNode.x0 + focusNode.x1) / 2
    : width / 2;

  const focusCy = focusNode
    ? (focusNode.y0 + focusNode.y1) / 2
    : height / 2;

  const cardX = Math.max(10, focusCx - cardWidth / 2);
  const cardY = Math.max(10, focusCy - cardHeight / 2);
  
  // Reserve a guaranteed footer area and compute buttonY BEFORE rendering content
  const buttonHeight = 30;
  const buttonWidth = 120;
  const buttonSpacing = 12;
  const buttonY = cardY + cardHeight - padding - buttonHeight;
  
  // Calculate available content height (subtract title, subtitle, buttons, padding)
  const availableContentHeight = cardHeight - headerHeight - footerHeight - padding * 2;
  
  // Card background
  const card = svg.append("g")
    .attr("class", "detail-card");
  
  card.append("rect")
    .attr("x", cardX)
    .attr("y", cardY)
    .attr("width", cardWidth)
    .attr("height", cardHeight)
    .attr("rx", cornerRadius)
    .attr("ry", cornerRadius)
    .attr("fill", "#ffffff")
    .attr("stroke", "#e0e0e0")
    .attr("stroke-width", 1);
  
  // Title
  const titleY = cardY + padding + 12;
  card.append("text")
    .attr("x", cardX + padding)
    .attr("y", titleY)
    .attr("font-size", "20px")
    .attr("font-weight", "600")
    .attr("fill", "#333")
    .text(payload.name || "Setting");
  
  // Breadcrumb/subtitle
  const subtitleY = titleY + 20;
  card.append("text")
    .attr("x", cardX + padding)
    .attr("y", subtitleY)
    .attr("font-size", "14px")
    .attr("fill", "#666")
    .text(breadcrumb || "");
  
  // Body content
  let currentY = subtitleY + 30;
  const lineSpacing = 20;
  const labelWidth = 100;
  const contentX = cardX + padding + labelWidth;
  const contentWidth = cardWidth - padding * 2 - labelWidth;
  
  // State
  card.append("text")
    .attr("x", cardX + padding)
    .attr("y", currentY)
    .attr("font-size", "13px")
    .attr("font-weight", "600")
    .attr("fill", "#666")
    .text("State:");
  card.append("text")
    .attr("x", contentX)
    .attr("y", currentY)
    .attr("font-size", "13px")
    .attr("fill", "#333")
    .text(payload.state || "N/A");
  currentY += lineSpacing;
  
  // Type/Actionability
  card.append("text")
    .attr("x", cardX + padding)
    .attr("y", currentY)
    .attr("font-size", "13px")
    .attr("font-weight", "600")
    .attr("fill", "#666")
    .text("Type:");
  card.append("text")
    .attr("x", contentX)
    .attr("y", currentY)
    .attr("font-size", "13px")
    .attr("fill", "#333")
    .text(payload.actionable || "Unknown");
  currentY += lineSpacing;
  
  // Risk
  if (payload.risk) {
    card.append("text")
      .attr("x", cardX + padding)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("font-weight", "600")
      .attr("fill", "#666")
      .text("Risk:");
    card.append("text")
      .attr("x", contentX)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("fill", "#333")
      .text(payload.risk);
    currentY += lineSpacing;
  }
  
  // Platform
  if (payload.platform) {
    card.append("text")
      .attr("x", cardX + padding)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("font-weight", "600")
      .attr("fill", "#666")
      .text("Platform:");
    card.append("text")
      .attr("x", contentX)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("fill", "#333")
      .text(payload.platform.charAt(0).toUpperCase() + payload.platform.slice(1));
    currentY += lineSpacing;
  }
  
  // Category
  if (payload.category) {
    card.append("text")
      .attr("x", cardX + padding)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("font-weight", "600")
      .attr("fill", "#666")
      .text("Category:");
    card.append("text")
      .attr("x", contentX)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("fill", "#333")
      .text(payload.category.replace(/_/g, ' '));
    currentY += lineSpacing;
  }
  
  // Clicks
  if (payload.clicks !== undefined && payload.clicks !== null) {
    card.append("text")
      .attr("x", cardX + padding)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("font-weight", "600")
      .attr("fill", "#666")
      .text("Clicks:");
    card.append("text")
      .attr("x", contentX)
      .attr("y", currentY)
      .attr("font-size", "13px")
      .attr("fill", "#333")
      .text(payload.clicks.toString());
    currentY += lineSpacing;
  }
  
  // Description
  currentY += 10;
  const descLabelY = currentY;
  card.append("text")
    .attr("x", cardX + padding)
    .attr("y", currentY)
    .attr("font-size", "13px")
    .attr("font-weight", "600")
    .attr("fill", "#666")
    .text("Description:");
  currentY += 20;
  
  // Calculate max height for description - clamp so it NEVER overlaps the footer/buttons
  const maxDescHeight = Math.max(
    40,
    (buttonY - 10) - currentY
  );
  const descriptionText = (payload.description || "No description available.");
  
  // Create a clipping path for the description area
  const descClipId = "desc-clip-" + Date.now();
  const descClip = svg.append("defs").append("clipPath")
    .attr("id", descClipId)
    .attr("clipPathUnits", "userSpaceOnUse");
  descClip.append("rect")
    .attr("x", cardX + padding)
    .attr("y", currentY - 15)
    .attr("width", cardWidth - padding * 2)
    .attr("height", maxDescHeight);
  
  const descText = card.append("text")
    .attr("x", cardX + padding)
    .attr("y", currentY)
    .attr("font-size", "13px")
    .attr("fill", "#333")
    .attr("dy", "0em")
    .attr("clip-path", `url(#${descClipId})`);
  wrapText(descText, descriptionText, cardWidth - padding * 2, maxDescHeight);
  
  // Add a footer background strip to make buttons pop
  card.append("rect")
    .attr("x", cardX)
    .attr("y", buttonY - 14)
    .attr("width", cardWidth)
    .attr("height", buttonHeight + 28)
    .attr("fill", "#ffffff")
    .attr("opacity", 0.95);
  
  // Back button - make it more prominent
  const backButton = card.append("g")
    .attr("class", "detail-button")
    .attr("cursor", "pointer")
    .on("click", function(e) {
      e.stopPropagation();
      exitDetailView();
    });
  
  backButton.append("rect")
    .attr("x", cardX + padding)
    .attr("y", buttonY)
    .attr("width", buttonWidth)
    .attr("height", buttonHeight)
    .attr("rx", 4)
    .attr("ry", 4)
    .attr("fill", "#4c6ef5")
    .attr("stroke", "#4c6ef5")
    .attr("stroke-width", 1);
  
  backButton.append("text")
    .attr("x", cardX + padding + buttonWidth / 2)
    .attr("y", buttonY + buttonHeight / 2)
    .attr("text-anchor", "middle")
    .attr("dominant-baseline", "middle")
    .attr("font-size", "13px")
    .attr("font-weight", "500")
    .attr("fill", "#ffffff")
    .text("← Back");
  
  // Force back button to front
  backButton.raise();
  
  // Open URL button (only if URL exists)
  if (payload.url) {
    const urlButton = card.append("g")
      .attr("class", "detail-button")
      .attr("cursor", "pointer")
      .on("click", function(e) {
        e.stopPropagation();
        window.open(payload.url, "_blank");
      })
      .on("mouseover", function() {
        d3.select(this).select("rect")
          .attr("fill", "#3b5bdb")
          .attr("stroke", "#3b5bdb");
      })
      .on("mouseout", function() {
        d3.select(this).select("rect")
          .attr("fill", "#4c6ef5")
          .attr("stroke", "#4c6ef5");
      });
    
    // Add tooltip for URL button (name only)
    createSVGButtonTooltip(urlButton, "Open URL");
    
    urlButton.append("rect")
      .attr("x", cardX + cardWidth - padding - buttonWidth)
      .attr("y", buttonY)
      .attr("width", buttonWidth)
      .attr("height", buttonHeight)
      .attr("rx", 4)
      .attr("ry", 4)
      .attr("fill", "#4c6ef5")
      .attr("stroke", "#4c6ef5")
      .attr("stroke-width", 1);
    
    urlButton.append("text")
      .attr("x", cardX + cardWidth - padding - buttonWidth / 2)
      .attr("y", buttonY + buttonHeight / 2)
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", "14px")
      .attr("font-weight", "500")
      .attr("fill", "#ffffff")
      .text("Open URL →");
    
    // Force URL button to front
    urlButton.raise();
  }
  
  // Escape key hint - only show if there's space
  if (buttonY + buttonHeight + 15 < cardY + cardHeight) {
    card.append("text")
      .attr("x", cardX + cardWidth / 2)
      .attr("y", buttonY + buttonHeight + 12)
      .attr("text-anchor", "middle")
      .attr("font-size", "10px")
      .attr("fill", "#999")
      .text("Press Esc to go back");
  }
}

/**
 * Render treemap visualization
 */
function renderTreemap() {
    if (!currentRoot) {
      buildHierarchy();
    }
  
    // Clean up any existing tooltips
    d3.selectAll(".treemap-tooltip").remove();
    
    // Hide area evidence panel
    hideAreaEvidence();
  
    const container = d3.select("#treemapContainer");
    // Remove all SVG content but preserve the area evidence panel
    container.selectAll("svg").remove();
    // Reset area evidence panel reference if it was removed, and hide it
    if (areaEvidenceEl) {
      if (!areaEvidenceEl.parentNode) {
        areaEvidenceEl = null;
      } else {
        // Hide panel when treemap is re-rendered
        hideAreaEvidence();
      }
    }
  
    const width = container.node().getBoundingClientRect().width || 1200;
    const height = 700;
  
    const svg = container.append("svg")
      .attr("width", width)
      .attr("height", height);
  
    // Check if we should render detail view instead of treemap
    if (isDetailView && detailPayload) {
      renderDetailView(svg, width, height, detailPayload, detailBreadcrumb, detailNode);
      return;
    }
  
    const g = svg.append("g");
  
    // Root state for this render pass
    const atRootNow = zoomStack.length === 0;
    
    // Platform normalization helper
    function normalizePlatformKey(p) {
      const k = (p || "unknown").trim().toLowerCase();
      if (k === "twitter") return "twitterx"; // optional mapping
      return k;
    }
    
    // Leaf hover state flag
    let isLeafHoverActive = false;
    
    // Helper to check if element is inside evidence actions area (safe hover zone)
    // Only the actions area (buttons/links) is a safe zone, not the panel body
    function isInsideEvidenceActions(el) {
      if (!el) return false;
      return el.closest && el.closest(".area-evidence-actions") !== null;
    }
    
    // Helper functions for area evidence (need access to g)
    function computeCategoryPlatformAreas(catNode) {
      const leaves = catNode.leaves ? catNode.leaves() : [];
      const perPlatform = new Map();
      let totalArea = 0;
      
      leaves.forEach(leaf => {
        const area = leafPixelArea(leaf);
        totalArea += area;
        
        const platform = (leaf.data.platform || "unknown").toLowerCase();
        if (!perPlatform.has(platform)) {
          perPlatform.set(platform, {
            platform: platform,
            totalArea: 0,
            leaves: []
          });
        }
        
        const platformData = perPlatform.get(platform);
        platformData.totalArea += area;
        
        const w = Math.max(0, leaf.x1 - leaf.x0);
        const h = Math.max(0, leaf.y1 - leaf.y0);
        platformData.leaves.push({
          name: leaf.data.name || leaf.data.setting || "Setting",
          w: Math.round(w),
          h: Math.round(h),
          area: Math.round(area)
        });
      });
      
      // Sort leaves by area descending for each platform
      perPlatform.forEach(platformData => {
        platformData.leaves.sort((a, b) => b.area - a.area);
      });
      
      return {
        perPlatform: perPlatform,
        totalArea: totalArea,
        leavesCount: leaves.length
      };
    }
    
    function dimAllCells() {
      g.selectAll("rect.treemap-cell").style("opacity", 0.2);
      g.selectAll("text.treemap-label").style("opacity", 0.2);
    }
    
    function restoreAllCells() {
      g.selectAll("rect.treemap-cell").style("opacity", 1);
      g.selectAll("text.treemap-label").style("opacity", 1);
      hideAreaEvidence();
    }
    
    function dimAllLeaves() {
      g.selectAll("g").each(function(d) {
        const isLeaf = !d.children || d.children.length === 0;
        if (isLeaf) {
          d3.select(this).select("rect.treemap-cell").style("opacity", 0.2);
          d3.select(this).select("text.treemap-label").style("opacity", 0.2);
        }
      });
    }
    
    function restoreAllLeaves() {
      g.selectAll("g").each(function(d) {
        const isLeaf = !d.children || d.children.length === 0;
        if (isLeaf) {
          d3.select(this).select("rect.treemap-cell").style("opacity", 1);
          d3.select(this).select("text.treemap-label").style("opacity", 1);
        }
      });
      hideAreaEvidence();
      isLeafHoverActive = false;
    }
    
    function getCategoryNodeForLeaf(leafNode) {
      if (!leafNode || !leafNode.parent) return null;
      return leafNode.parent;
    }
    
    function highlightLeavesByCategoryAndPlatform(catNode, platformKey) {
      g.selectAll("g").each(function(d) {
        const isLeaf = !d.children || d.children.length === 0;
        if (isLeaf && d.parent === catNode && normalizePlatformKey(d.data.platform) === platformKey) {
          d3.select(this).select("rect.treemap-cell").style("opacity", 1);
          d3.select(this).select("text.treemap-label").style("opacity", 1);
        }
      });
    }
    
    function computeSubsetArea(catNode, platformKey) {
      const leaves = catNode.leaves ? catNode.leaves() : [];
      const matchingLeaves = leaves.filter(leaf => 
        normalizePlatformKey(leaf.data.platform) === platformKey
      );
      
      let totalArea = 0;
      const topLeaves = [];
      
      matchingLeaves.forEach(leaf => {
        const area = leafPixelArea(leaf);
        totalArea += area;
        
        const w = Math.max(0, leaf.x1 - leaf.x0);
        const h = Math.max(0, leaf.y1 - leaf.y0);
        topLeaves.push({
          name: leaf.data.name || leaf.data.setting || "Setting",
          w: Math.round(w),
          h: Math.round(h),
          area: Math.round(area)
        });
      });
      
      // Sort by area descending
      topLeaves.sort((a, b) => b.area - a.area);
      
      return {
        totalArea: totalArea,
        leavesCount: matchingLeaves.length,
        topLeaves: topLeaves.slice(0, 3) // Top 3
      };
    }
    
    function highlightCategoryLeaves(catNode) {
      const catLeaves = catNode.leaves ? catNode.leaves() : [];
      const leafSet = new Set(catLeaves);
      
      g.selectAll("g").each(function(d) {
        const isLeaf = !d.children || d.children.length === 0;
        if (isLeaf && leafSet.has(d)) {
          d3.select(this).select("rect.treemap-cell").style("opacity", 1);
          d3.select(this).select("text.treemap-label").style("opacity", 1);
        }
      });
    }
    
    function renderAreaEvidence(catNode) {
      const categoryName = (catNode.data.name || "Category").replace(/_/g, ' ');
      const areas = computeCategoryPlatformAreas(catNode);
      
      let body = `
        <div class="area-evidence-row">
          <strong>Total area:</strong> ${fmtInt(Math.round(areas.totalArea))} px²<br/>
          <strong>Leaf count:</strong> ${fmtInt(areas.leavesCount)}
        </div>
      `;
      
      // Sort platforms by area descending
      const platformEntries = Array.from(areas.perPlatform.entries())
        .sort((a, b) => b[1].totalArea - a[1].totalArea);
      
      platformEntries.forEach(([platformKey, platformData]) => {
        const platformName = platformKey.charAt(0).toUpperCase() + platformKey.slice(1);
        const percentage = areas.totalArea > 0 
          ? ((platformData.totalArea / areas.totalArea) * 100).toFixed(1) 
          : "0.0";
        const leafCount = platformData.leaves.length;
        
        body += `
          <div class="area-evidence-platform">
            <strong>${platformName}</strong><br/>
            ${fmtInt(Math.round(platformData.totalArea))} px² (${percentage}%)<br/>
            <span class="area-evidence-eq">Area = Σ((x1-x0)×(y1-y0)) over ${leafCount} leaf rectangle${leafCount !== 1 ? 's' : ''}</span>
        `;
        
        // Top 3 largest contributing leaves
        const topLeaves = platformData.leaves.slice(0, 3);
        if (topLeaves.length > 0) {
          body += `<div style="margin-top: 4px; font-size: 11px; color: #666;">`;
          topLeaves.forEach(leaf => {
            body += `• ${leaf.name}: <span class="area-evidence-eq">(${leaf.w}×${leaf.h})=${fmtInt(leaf.area)}</span><br/>`;
          });
          body += `</div>`;
        }
        
        body += `</div>`;
      });
      
      showAreaEvidence(categoryName, body);
    }
  
    // Get unique platforms and categories
    const platforms = Array.from(new Set(allData.map(d => d.platform))).sort();
    const categories = Array.from(new Set(allData.map(d => d.category)));
  
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
        const baseColor = PLATFORM_COLORS[platform] || PLATFORM_COLORS.unknown;
  
        return d3.color(baseColor);
      })
      .attr("stroke", d => {
        if (d.data.stateType === "navigational") return "#4CAF50";
        if (d.data.stateType === "actionable") return "#2196F3";
        return "#fff";
      })
      .attr("stroke-width", d => (d.data.stateType ? 2 : 1.5))
      .attr("stroke-dasharray", d => (d.data.stateType === "navigational" ? "4,2" : "none"))
      .on("mouseover", function(event, d) {
        const isLeaf = !d.children || d.children.length === 0;
        if (!isLeaf) return;
        
        // If in detail view, do nothing
        if (isDetailView) return;
        
        // Get setting name
        const settingName = d.data.name || d.data.setting || d.data.meta?.setting || "Setting";
        
        // Create or get tooltip
        let tooltip = d3.select("body").select(".treemap-tooltip");
        if (tooltip.empty()) {
          tooltip = d3.select("body").append("div")
            .attr("class", "treemap-tooltip")
            .style("opacity", 0)
            .style("position", "absolute")
            .style("background", "rgba(0, 0, 0, 0.85)")
            .style("color", "white")
            .style("padding", "8px 12px")
            .style("border-radius", "4px")
            .style("font-size", "13px")
            .style("pointer-events", "none")
            .style("z-index", "1000")
            .style("max-width", "300px");
        }
        
        tooltip
          .html(settingName)
          .style("opacity", 1)
          .style("left", (event.pageX + 10) + "px")
          .style("top", (event.pageY - 10) + "px");
      })
      .on("mousemove", function(event) {
        const tooltip = d3.select("body").select(".treemap-tooltip");
        if (!tooltip.empty()) {
          tooltip
            .style("left", (event.pageX + 10) + "px")
            .style("top", (event.pageY - 10) + "px");
        }
      })
      .on("mouseout", function() {
        d3.select("body").select(".treemap-tooltip")
          .style("opacity", 0);
      })
      .on("click", function(event, d) {
        event.stopPropagation();
        event.preventDefault();
  
        const isLeaf = !d.children || d.children.length === 0;
        if (!isLeaf && d.children && d.children.length > 0) {
          // Non-leaf: exit detail view if active, then zoom
          if (isDetailView) {
            exitDetailView();
          }
          zoomInto(d);
        } else {
          // Leaf: enter detail view
          enterDetailView(d);
        }
      })
      .style("cursor", d => {
        const isLeaf = !d.children || d.children.length === 0;
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
          if (isDetailView) {
            exitDetailView();
          }
          zoomInto(d);
        })
        .on("mouseover", function(event, d) {
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
      const isLeaf = !d.children || d.children.length === 0;
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
  
    // Tooltip handlers removed - replaced with area evidence panel on category hover
  
    updateBreadcrumbs();
    renderLegend(platforms, categories);
    renderBelowTreemapCharts();
  }
  

/**
 * Render legend showing platforms (with colors) and categories
 */
function renderLegend(platforms, categories) {
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
      .style("background", PLATFORM_COLORS[platform] || PLATFORM_COLORS.unknown)
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
 * Render charts below treemap (stacked bar and small multiples)
 */
function renderBelowTreemapCharts() {
  const filtered = getFilteredData();
  renderStackedPlatformChart(filtered);
  renderCoverageHeatmap(filtered);
}

/**
 * Render stacked bar chart: actionable vs navigational vs unknown counts per platform
 */
function renderStackedPlatformChart(filteredData) {
  const container = d3.select("#stackedPlatformChart");
  container.selectAll("*").remove();

  if (!filteredData || filteredData.length === 0) {
    container.append("p")
      .style("padding", "20px")
      .style("color", "#666")
      .text("No data available after filtering.");
    return;
  }

  // Prepare data: group by platform and count by stateType
  const platformMap = new Map();
  filteredData.forEach(d => {
    const platform = d.platform || "unknown";
    if (!platformMap.has(platform)) {
      platformMap.set(platform, {
        platform: platform,
        actionable: 0,
        navigational: 0,
        unknown: 0
      });
    }
    const counts = platformMap.get(platform);
    const stateType = d.stateType || "unknown";
    if (stateType === "actionable") counts.actionable++;
    else if (stateType === "navigational") counts.navigational++;
    else counts.unknown++;
  });

  const data = Array.from(platformMap.values())
    .map(d => ({
      platform: d.platform,
      actionable: d.actionable,
      navigational: d.navigational,
      unknown: d.unknown,
      total: d.actionable + d.navigational + d.unknown
    }))
    .sort((a, b) => b.total - a.total);

  if (data.length === 0) {
    container.append("p")
      .style("padding", "20px")
      .style("color", "#666")
      .text("No data available after filtering.");
    return;
  }

  // Set up dimensions
  const margin = { top: 20, right: 20, bottom: 60, left: 50 };
  const width = container.node().getBoundingClientRect().width || 600;
  const height = 400;
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  // Create SVG
  const svg = container.append("svg")
    .attr("width", width)
    .attr("height", height);

  const g = svg.append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  // Scales
  const xScale = d3.scaleBand()
    .domain(data.map(d => d.platform))
    .range([0, innerWidth])
    .padding(0.2);

  const maxTotal = d3.max(data, d => d.total) || 1;
  const yScale = d3.scaleLinear()
    .domain([0, maxTotal])
    .nice()
    .range([innerHeight, 0]);

  // Stack keys
  const stackKeys = ["actionable", "navigational", "unknown"];
  const stack = d3.stack()
    .keys(stackKeys)
    .order(d3.stackOrderNone)
    .offset(d3.stackOffsetNone);

  const stackedData = stack(data);

  // Color scale for stack layers
  const colorScale = d3.scaleOrdinal()
    .domain(stackKeys)
    .range(["#2196F3", "#4CAF50", "#9E9E9E"]);

  // Create or reuse tooltip
  let tooltip = d3.select("body").select(".stacked-chart-tooltip");
  if (tooltip.empty()) {
    tooltip = d3.select("body").append("div")
      .attr("class", "stacked-chart-tooltip");
  }
  tooltip
    .style("position", "absolute")
    .style("padding", "8px 12px")
    .style("background", "rgba(0, 0, 0, 0.85)")
    .style("color", "#fff")
    .style("border-radius", "4px")
    .style("font-size", "12px")
    .style("pointer-events", "none")
    .style("opacity", 0)
    .style("z-index", 1000);

  // Draw bars
  const layers = g.selectAll(".layer")
    .data(stackedData)
    .enter()
    .append("g")
    .attr("class", "layer")
    .attr("fill", d => colorScale(d.key));

  layers.selectAll("rect")
    .data(d => d)
    .enter()
    .append("rect")
    .attr("x", d => xScale(d.data.platform))
    .attr("y", d => yScale(d[1]))
    .attr("height", d => yScale(d[0]) - yScale(d[1]))
    .attr("width", xScale.bandwidth())
    .on("mouseover", function(event, d) {
      const platform = d.data.platform;
      const key = d3.select(this.parentNode).datum().key;
      const value = d[1] - d[0];
      const total = d.data.total;
      const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;

      tooltip.transition()
        .duration(200)
        .style("opacity", 1);

      tooltip.html(`
        <strong>${platform.charAt(0).toUpperCase() + platform.slice(1)}</strong><br/>
        ${key.charAt(0).toUpperCase() + key.slice(1)}: ${value} (${percentage}%)<br/>
        Total: ${total}
      `)
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px");
    })
    .on("mousemove", function(event) {
      tooltip
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px");
    })
    .on("mouseout", function() {
      tooltip.transition()
        .duration(200)
        .style("opacity", 0);
    });

  // X-axis
  g.append("g")
    .attr("transform", `translate(0,${innerHeight})`)
    .call(d3.axisBottom(xScale))
    .selectAll("text")
    .style("text-anchor", "end")
    .attr("dx", "-.8em")
    .attr("dy", ".15em")
    .attr("transform", "rotate(-45)")
    .style("font-size", "11px");

  // Y-axis
  g.append("g")
    .call(d3.axisLeft(yScale).ticks(5))
    .style("font-size", "11px");

  // Y-axis label
  g.append("text")
    .attr("transform", "rotate(-90)")
    .attr("y", 0 - margin.left)
    .attr("x", 0 - (innerHeight / 2))
    .attr("dy", "1em")
    .style("text-anchor", "middle")
    .style("font-size", "12px")
    .text("Count of Settings");

  // Legend
  const legend = g.append("g")
    .attr("transform", `translate(${innerWidth - 150}, 10)`);

  const legendItems = legend.selectAll(".legend-item")
    .data(stackKeys)
    .enter()
    .append("g")
    .attr("class", "legend-item")
    .attr("transform", (d, i) => `translate(0, ${i * 20})`);

  legendItems.append("rect")
    .attr("width", 12)
    .attr("height", 12)
    .attr("fill", d => colorScale(d));

  legendItems.append("text")
    .attr("x", 16)
    .attr("y", 9)
    .style("font-size", "11px")
    .text(d => d.charAt(0).toUpperCase() + d.slice(1));
}

/**
 * Render coverage heatmap: platforms (rows) vs top N setting names (columns)
 * Cell value encodes: 0=missing, 1=navigational, 2=actionable, 3=unknown
 */
function renderCoverageHeatmap(filteredData) {
  const container = d3.select("#categorySmallMultiples");
  container.selectAll("*").remove();

  if (!filteredData || filteredData.length === 0) {
    container.append("p")
      .style("padding", "20px")
      .style("color", "#666")
      .text("No data for current filters.");
    return;
  }

  // Configuration: top N settings to show
  const TOP_N_SETTINGS = 30;

  // Build list of platforms (sorted, prefer order from PLATFORM_COLORS)
  const platformOrder = Object.keys(PLATFORM_COLORS);
  const platformsSet = new Set(filteredData.map(d => (d.platform || "unknown").trim().toLowerCase()));
  const platforms = platformOrder.filter(p => platformsSet.has(p))
    .concat(Array.from(platformsSet).filter(p => !platformOrder.includes(p)).sort());

  if (platforms.length === 0) {
    container.append("p")
      .style("padding", "20px")
      .style("color", "#666")
      .text("No data for current filters.");
    return;
  }

  // Build list of top N setting names by frequency
  const settingCounts = new Map();
  filteredData.forEach(d => {
    const settingName = (d.setting || "").trim();
    if (settingName) {
      const key = settingName.toLowerCase(); // Normalize for counting
      settingCounts.set(key, (settingCounts.get(key) || 0) + 1);
    }
  });

  // Get top N settings (preserve original capitalization from first occurrence)
  const settingNameMap = new Map(); // lowercase -> original
  filteredData.forEach(d => {
    const settingName = (d.setting || "").trim();
    if (settingName) {
      const key = settingName.toLowerCase();
      if (!settingNameMap.has(key)) {
        settingNameMap.set(key, settingName);
      }
    }
  });

  const topSettings = Array.from(settingCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, TOP_N_SETTINGS)
    .map(([key]) => settingNameMap.get(key))
    .filter(Boolean);

  if (topSettings.length === 0) {
    container.append("p")
      .style("padding", "20px")
      .style("color", "#666")
      .text("No data for current filters.");
    return;
  }

  // Build lookup: platform+setting -> best stateType
  // Priority: actionable > navigational > unknown
  const coverageMap = new Map();
  const urlMap = new Map(); // Store first URL found for each platform+setting
  const countMap = new Map(); // Count occurrences

  filteredData.forEach(d => {
    const platform = (d.platform || "unknown").trim().toLowerCase();
    const settingName = (d.setting || "").trim();
    if (!settingName) return;

    const key = `${platform}::${settingName.toLowerCase()}`;
    const currentStateType = (d.stateType || "unknown").toLowerCase();
    
    // Count occurrences
    countMap.set(key, (countMap.get(key) || 0) + 1);
    
    if (!coverageMap.has(key)) {
      coverageMap.set(key, currentStateType);
      if (d.url) {
        urlMap.set(key, d.url);
      }
    } else {
      // Update if we have a "better" stateType
      const existing = coverageMap.get(key);
      const priority = { actionable: 3, navigational: 2, unknown: 1 };
      if (priority[currentStateType] > priority[existing]) {
        coverageMap.set(key, currentStateType);
        if (d.url && !urlMap.has(key)) {
          urlMap.set(key, d.url);
        }
      }
    }
  });

  // Build matrix data
  const matrix = platforms.map(platform => {
    return topSettings.map(settingName => {
      const key = `${platform}::${settingName.toLowerCase()}`;
      const stateType = coverageMap.get(key);
      
      let value = 0; // missing
      if (stateType === "actionable") value = 2;
      else if (stateType === "navigational") value = 1;
      else if (stateType === "unknown") value = 3;

      return {
        platform,
        setting: settingName,
        value,
        url: urlMap.get(key) || null,
        count: countMap.get(key) || 0
      };
    });
  });

  // Set up dimensions
  const containerWidth = container.node().getBoundingClientRect().width || 600;
  const margin = { top: 80, right: 20, bottom: 120, left: 120 };
  const width = containerWidth - margin.left - margin.right;
  const height = Math.max(400, platforms.length * 25 + margin.top + margin.bottom) - margin.top - margin.bottom;

  // Create SVG
  const svg = container.append("svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom);

  const g = svg.append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

  // Scales
  const xScale = d3.scaleBand()
    .domain(topSettings)
    .range([0, width])
    .padding(0.05);

  const yScale = d3.scaleBand()
    .domain(platforms)
    .range([0, height])
    .padding(0.05);

  // Color scale
  const colorScale = d3.scaleOrdinal()
    .domain([0, 1, 2, 3])
    .range(["#f2f2f2", "#4CAF50", "#2196F3", "#9E9E9E"]);

  // Create or reuse tooltip
  let tooltip = d3.select("body").select(".heatmap-tooltip");
  if (tooltip.empty()) {
    tooltip = d3.select("body").append("div")
      .attr("class", "heatmap-tooltip");
  }
  tooltip
    .style("position", "absolute")
    .style("padding", "8px 12px")
    .style("background", "rgba(0, 0, 0, 0.85)")
    .style("color", "#fff")
    .style("border-radius", "4px")
    .style("font-size", "12px")
    .style("pointer-events", "none")
    .style("opacity", 0)
    .style("z-index", 1000);

  // Draw cells
  const cells = g.selectAll(".cell")
    .data(matrix.flat())
    .enter()
    .append("rect")
    .attr("class", "cell")
    .attr("x", d => xScale(d.setting))
    .attr("y", d => yScale(d.platform))
    .attr("width", xScale.bandwidth())
    .attr("height", yScale.bandwidth())
    .attr("fill", d => colorScale(d.value))
    .attr("stroke", "#fff")
    .attr("stroke-width", 0.5)
    .style("cursor", d => d.value > 0 && d.url ? "pointer" : "default")
    .on("mouseover", function(event, d) {
      const statusMap = {
        0: "Missing",
        1: "Navigational",
        2: "Actionable",
        3: "Unknown"
      };

      tooltip.transition()
        .duration(200)
        .style("opacity", 1);

      let tooltipHtml = `
        <strong>${d.platform.charAt(0).toUpperCase() + d.platform.slice(1)}</strong><br/>
        <strong>${d.setting}</strong><br/>
        Status: ${statusMap[d.value]}<br/>
        Count: ${d.count}
      `;
      
      if (d.url) {
        tooltipHtml += `<br/><em style="font-size: 10px; color: #ccc;">Click to open URL</em>`;
      }

      tooltip.html(tooltipHtml)
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px");

      d3.select(this)
        .attr("stroke-width", 2)
        .attr("stroke", "#333");
    })
    .on("mousemove", function(event) {
      tooltip
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 10) + "px");
    })
    .on("mouseout", function() {
      tooltip.transition()
        .duration(200)
        .style("opacity", 0);

      d3.select(this)
        .attr("stroke-width", 0.5)
        .attr("stroke", "#fff");
    })
    .on("click", function(event, d) {
      if (d.value > 0 && d.url) {
        window.open(d.url, "_blank");
      }
    });

  // X-axis (setting names at bottom, rotated)
  g.append("g")
    .attr("transform", `translate(0,${height})`)
    .call(d3.axisBottom(xScale))
    .selectAll("text")
    .style("text-anchor", "end")
    .attr("dx", "-.8em")
    .attr("dy", ".15em")
    .attr("transform", "rotate(-45)")
    .style("font-size", "10px")
    .text(d => {
      // Truncate long setting names
      const maxLen = 20;
      return d.length > maxLen ? d.substring(0, maxLen - 3) + "..." : d;
    });

  // Y-axis (platform names on left)
  g.append("g")
    .call(d3.axisLeft(yScale))
    .selectAll("text")
    .style("font-size", "11px")
    .text(d => d.charAt(0).toUpperCase() + d.slice(1));

  // Legend
  const legendData = [
    { label: "Missing", value: 0 },
    { label: "Navigational", value: 1 },
    { label: "Actionable", value: 2 },
    { label: "Unknown", value: 3 }
  ];

  const legend = g.append("g")
    .attr("class", "legend")
    .attr("transform", `translate(${width - 180}, -60)`);

  const legendItems = legend.selectAll(".legend-item")
    .data(legendData)
    .enter()
    .append("g")
    .attr("class", "legend-item")
    .attr("transform", (d, i) => `translate(0, ${i * 20})`);

  legendItems.append("rect")
    .attr("width", 14)
    .attr("height", 14)
    .attr("fill", d => colorScale(d.value))
    .attr("stroke", "#fff")
    .attr("stroke-width", 0.5);

  legendItems.append("text")
    .attr("x", 18)
    .attr("y", 11)
    .style("font-size", "11px")
    .text(d => d.label);
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
      meta: child.data.meta,
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
                const saved = zoomStack.pop();
                currentRoot = saved.root;
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
 * Populate platform filter dropdown with unique platforms from data
 */
function populatePlatformFilter() {
  const platformFilterSelect = document.getElementById("platformFilter");
  if (!platformFilterSelect) {
    console.warn("platformFilter element not found");
    return;
  }
  
  // Get unique platforms and sort them
  const platforms = Array.from(new Set(allData.map(d => d.platform)))
    .filter(p => p && p !== 'unknown')
    .sort();
  
  // Preserve current selections (array of selected values)
  const currentSelections = Array.from(platformFilterSelect.selectedOptions)
    .map(option => option.value);
  
  // Build options HTML
  let optionsHTML = '<option value="all">All</option>';
  platforms.forEach(platform => {
    const selected = currentSelections.includes(platform) ? ' selected' : '';
    const displayName = platform.charAt(0).toUpperCase() + platform.slice(1);
    optionsHTML += `<option value="${platform}"${selected}>${displayName}</option>`;
  });
  
  // Update dropdown
  platformFilterSelect.innerHTML = optionsHTML;
  
  // Restore selections if they still exist
  if (currentSelections.length > 0 && !currentSelections.includes('all')) {
    currentSelections.forEach(val => {
      const option = platformFilterSelect.querySelector(`option[value="${val}"]`);
      if (option) {
        option.selected = true;
      }
    });
    // Update the filter state
    currentPlatformFilter = currentSelections.filter(p => platforms.includes(p));
    if (currentPlatformFilter.length === 0) {
      currentPlatformFilter = ['all'];
      platformFilterSelect.querySelector('option[value="all"]').selected = true;
    }
  } else {
    // Default to "all" if no valid selections
    currentPlatformFilter = ['all'];
    platformFilterSelect.querySelector('option[value="all"]').selected = true;
  }
}

/**
 * Setup event handlers - called after DOM is ready
 */
function setupEventHandlers() {
  // Initialize DOM references for details panel
  settingDetails = document.getElementById("settingDetails");
  detailsTitle = document.getElementById("detailsTitle");
  detailsSubtitle = document.getElementById("detailsSubtitle");
  detailsDescription = document.getElementById("detailsDescription");
  detailsState = document.getElementById("detailsState");
  detailsActionable = document.getElementById("detailsActionable");
  detailsRisk = document.getElementById("detailsRisk");
  detailsOpenUrl = document.getElementById("detailsOpenUrl");
  detailsClose = document.getElementById("detailsClose");
  
  // Initialize panel as hidden
  if (settingDetails) {
    settingDetails.classList.add("hidden");
  }
  
  // Close button handler
  if (detailsClose) {
    detailsClose.addEventListener("click", function(e) {
      e.preventDefault();
      e.stopPropagation();
      closeDetails();
    });
  }
  
  // Escape key handler
  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape") {
      if (isDetailView) {
        exitDetailView();
      } else if (settingDetails && !settingDetails.classList.contains("hidden")) {
        closeDetails();
      }
    }
  });
  
  // Reset hover state when window loses focus (e.g., when opening URL in new tab)
  window.addEventListener("blur", function() {
    if (areaEvidenceEl && !areaEvidenceEl.classList.contains("hidden")) {
      hideAreaEvidence();
    }
  });
  
  // Reset hover state when window regains focus
  window.addEventListener("focus", function() {
    // Ensure panel is hidden and state is reset
    if (areaEvidenceEl) {
      hideAreaEvidence();
    }
  });
  
  // Prevent URL link from triggering zoom
  if (detailsOpenUrl) {
    detailsOpenUrl.addEventListener("click", function(e) {
      e.stopPropagation();
      // Allow default link behavior (open in new tab)
    });
  }
  
  const sizingMetricSelect = document.getElementById("sizingMetric");
  const stateTypeFilterSelect = document.getElementById("stateTypeFilter");
  const searchBox = document.getElementById("searchBox");
  const resetViewBtn = document.getElementById("resetView");
  const platformFilterSelect = document.getElementById("platformFilter");
  
  if (platformFilterSelect) {
    platformFilterSelect.addEventListener("change", function() {
      // Get all selected options
      const selectedOptions = Array.from(this.selectedOptions).map(opt => opt.value);
      
      // Handle "All" option logic
      if (selectedOptions.includes('all')) {
        // If "All" is selected along with other options, deselect "All" and keep others
        if (selectedOptions.length > 1) {
          this.querySelector('option[value="all"]').selected = false;
          const filtered = selectedOptions.filter(v => v !== 'all');
          currentPlatformFilter = filtered;
        } else {
          // Only "All" is selected - deselect everything else to be safe
          Array.from(this.options).forEach(opt => {
            if (opt.value !== 'all') {
              opt.selected = false;
            }
          });
          currentPlatformFilter = ['all'];
        }
      } else {
        // "All" is not selected
        if (selectedOptions.length === 0) {
          // No selection - default to "All"
          this.querySelector('option[value="all"]').selected = true;
          currentPlatformFilter = ['all'];
        } else {
          // Other platforms selected - use them
          currentPlatformFilter = selectedOptions;
        }
      }
      
      currentRoot = null;
      zoomStack = [];
      buildHierarchy();
      renderTreemap();
    });
  } else {
    console.warn("platformFilter element not found");
  }
  
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
    attachButtonNameTooltip(resetViewBtn);
    resetViewBtn.addEventListener("click", function() {
      currentRoot = null;
      zoomStack = [];
      currentSearchQuery = '';
      currentPlatformFilter = ['all'];
      if (searchBox) {
        searchBox.value = "";
      }
      if (platformFilterSelect) {
        // Deselect all options except "all"
        Array.from(platformFilterSelect.options).forEach(opt => {
          opt.selected = opt.value === 'all';
        });
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