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
let currentCategoryFilter = 'all';
let guidedMode = true; // Default: show guided walkthrough (one category at a time)
let revealedCategories = new Set(); // For guided (progressive reveal) mode

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

// Data source paths (JSON first, then CSV fallback)
// JSON: from explore/ use ../../database/data/..., from dashboard root use ../database/data/...
const jsonPaths = [
  "../../database/data/extracted_settings_with_urls_and_layers_classified.json",
  "../database/data/extracted_settings_with_urls_and_layers_classified.json"
];

const csvPaths = [
  "../database/data/all_platforms_classified.csv"
];

// Priority privacy CSV (flat: platform, toggle_name, description, state, click_counts, category, url) — used by explore page
const priorityCsvPaths = [
  "../../database/data/priority_privacy.csv",
  "../database/data/priority_privacy.csv"
];

function showLoadError(title, triedPaths) {
  const container = d3.select("#treemapContainer");
  container.html(`
    <div style='padding: 20px; color: #d32f2f;'>
      <p><strong>Error loading data:</strong> ${title}</p>
      <p style='margin-top: 10px; font-size: 13px; color: #666;'>
        <strong>Solution:</strong> This visualization requires a web server due to browser security restrictions.<br>
        Run from the project root: <code>python -m http.server 8000</code><br>
        Then open the explore or dashboard page.
      </p>
      <p style='margin-top: 10px; font-size: 12px; color: #666;'>
        Tried paths:<br>
        ${(triedPaths || []).map((p, i) => `${i + 1}. ${p}`).join('<br>')}
      </p>
    </div>
  `);
}

/**
 * Parse classified JSON into the same allData shape as parseCSVData
 * JSON shape: array of { platform, all_settings: [ { setting, description, state, url, layer, category } ] }
 */
function parseJSONData(jsonArray) {
  if (!Array.isArray(jsonArray)) {
    return [];
  }
  const settingsMap = new Map();
  jsonArray.forEach(platformBlock => {
    let platform = (platformBlock.platform || "unknown").trim().toLowerCase();
    if (platform === "google") platform = "googleaccount";
    if (platform === "twitter") platform = "twitterx";
    const settings = platformBlock.all_settings;
    if (!Array.isArray(settings)) return;
    settings.forEach(s => {
      const settingName = s.setting || "Unknown";
      const description = s.description || "";
      const state = s.state || "unknown";
      const category = (s.category || "unknown").trim();
      const url = s.url || "";
      const clicks = s.layer != null ? Number(s.layer) : 0; // layer = depth (equivalent to clicks)
      const key = `${platform}::${category}::${settingName}`;
      const stateType = determineStateType(state);
      if (!settingsMap.has(key)) {
        settingsMap.set(key, {
          platform,
          category,
          setting: settingName,
          description,
          state,
          stateType,
          url,
          clicks,
          weight: calculateWeight(stateType, category, currentSizingMetric, clicks)
        });
      } else {
        const existing = settingsMap.get(key);
        if (!existing.url && url) existing.url = url;
      }
    });
  });
  return Array.from(settingsMap.values());
}

function loadJSON(pathIndex = 0) {
  if (pathIndex >= jsonPaths.length) {
    console.warn("All JSON paths failed, falling back to CSV");
    loadCSV(0);
    return;
  }
  const jsonPath = jsonPaths[pathIndex];
  console.log("Attempting to load JSON from:", jsonPath);
  fetch(jsonPath)
    .then(res => {
      if (!res.ok) throw new Error(res.statusText);
      return res.json();
    })
    .then(data => {
      if (!data || (Array.isArray(data) && data.length === 0)) {
        throw new Error("JSON is empty");
      }
      allData = parseJSONData(data);
      console.log("JSON loaded:", data.length, "platform blocks →", allData.length, "unique settings");
      populatePlatformFilter();
      populateCategoryFilter();
      currentCategoryFilter = 'guided';
      guidedMode = true;
      const cats = getSortedCategories();
      revealedCategories = new Set(cats.length ? [cats[0]] : []);
      const catSelect = document.getElementById('categoryFilter');
      if (catSelect) catSelect.value = 'guided';
      const guidedEl = document.getElementById('guidedCategoryControls');
      if (guidedEl) guidedEl.classList.remove('hidden');
      buildHierarchy();
      renderTreemap();
    })
    .catch(err => {
      console.error("Failed to load JSON from " + jsonPath + ":", err);
      loadJSON(pathIndex + 1);
    });
}

function loadCSV(pathIndex = 0) {
  if (pathIndex >= csvPaths.length) {
    showLoadError("Could not find CSV file", csvPaths);
    return;
  }
  const csvPath = csvPaths[pathIndex];
  console.log("Attempting to load CSV from:", csvPath);
  d3.csv(csvPath).then(data => {
    console.log("CSV loaded successfully from:", csvPath);
    console.log("CSV rows:", data.length);
    if (!data || data.length === 0) {
      throw new Error("CSV file is empty");
    }
    allData = parseCSVData(data);
    console.log("Parsed data:", allData.length, "unique settings");
    populatePlatformFilter();
    populateCategoryFilter();
    currentCategoryFilter = 'guided';
    guidedMode = true;
    const cats = getSortedCategories();
    revealedCategories = new Set(cats.length ? [cats[0]] : []);
    const catSelect = document.getElementById('categoryFilter');
    if (catSelect) catSelect.value = 'guided';
    const guidedEl = document.getElementById('guidedCategoryControls');
    if (guidedEl) guidedEl.classList.remove('hidden');
    buildHierarchy();
    renderTreemap();
  }).catch(err => {
    console.error("Failed to load from " + csvPath + ":", err);
    loadCSV(pathIndex + 1);
  });
}

// Start loading: explore page uses priority_privacy.csv; other pages use JSON then CSV fallback
const isExplorePage = typeof window !== "undefined" && window.location.pathname.indexOf("explore") !== -1;
if (isExplorePage) {
  loadPriorityCSV(0);
} else {
  loadJSON();
}

/**
 * Parse priority_privacy.csv (flat rows: platform, toggle_name, description, state, click_counts, category, url)
 * into the same allData shape as parseCSVData / parseJSONData.
 * No deduplication: every row becomes one entry so all rows are shown.
 */
function parsePriorityCSVData(csvData) {
  if (!Array.isArray(csvData)) return [];
  return csvData.map(row => {
    let platform = (row.platform || "unknown").trim().toLowerCase();
    if (platform === "google") platform = "googleaccount";
    if (platform === "twitter") platform = "twitterx";
    const settingName = (row.toggle_name || row.setting || "Unknown").trim();
    const description = (row.description || "").trim();
    const state = (row.state || "unknown").trim();
    const category = (row.category || "unknown").trim();
    const url = (row.url || "").trim();
    const clicks = Math.max(0, parseInt(row.click_counts, 10) || 0);
    const stateType = determineStateType(state);
    return {
      platform,
      category,
      setting: settingName,
      description,
      state,
      stateType,
      url,
      clicks,
      weight: calculateWeight(stateType, category, currentSizingMetric, clicks)
    };
  });
}

function loadPriorityCSV(pathIndex) {
  if (pathIndex >= priorityCsvPaths.length) {
    showLoadError("Could not find priority_privacy.csv", priorityCsvPaths);
    return;
  }
  const csvPath = priorityCsvPaths[pathIndex];
  console.log("Attempting to load priority CSV from:", csvPath);
  d3.csv(csvPath).then(data => {
    if (!data || data.length === 0) {
      throw new Error("CSV file is empty");
    }
    allData = parsePriorityCSVData(data);
    console.log("Priority CSV loaded:", allData.length, "rows (no deduplication)");
    populatePlatformFilter();
    populateCategoryFilter();
    currentCategoryFilter = "guided";
    guidedMode = true;
    const cats = getSortedCategories();
    revealedCategories = new Set(cats.length ? [cats[0]] : []);
    const catSelect = document.getElementById("categoryFilter");
    if (catSelect) catSelect.value = "guided";
    const guidedEl = document.getElementById("guidedCategoryControls");
    if (guidedEl) guidedEl.classList.remove("hidden");
    buildHierarchy();
    renderTreemap();
  }).catch(err => {
    console.error("Failed to load priority CSV from " + csvPath + ":", err);
    loadPriorityCSV(pathIndex + 1);
  });
}

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
      stateLower === 'active' ||
      stateLower.includes('enabled') ||
      stateLower.includes('disabled') ||
      stateLower.includes('actionable') ||
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
 * Get sorted unique category keys from allData
 */
function getSortedCategories() {
  return Array.from(new Set(allData.map(d => d.category || 'unknown')))
    .filter(Boolean)
    .sort();
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
  
  // Apply category filter
  if (currentCategoryFilter === 'guided') {
    filtered = filtered.filter(d => revealedCategories.has(d.category));
  } else if (currentCategoryFilter !== 'all') {
    filtered = filtered.filter(d => d.category === currentCategoryFilter);
  }
  
  return filtered;
}

/**
 * Get leaf data from current treemap view, filtered by current filters
 * Returns the .data objects from currentRoot.leaves() after applying filters
 */
function getCurrentViewLeafData() {
  if (!currentRoot) {
    return [];
  }
  
  // Get leaves from current view
  const leaves = currentRoot.leaves ? currentRoot.leaves() : [];
  
  // Extract and normalize data from leaves
  // Leaf data structure: { name, meta: { platform, category, setting, ... }, platform, category, ... }
  let rows = leaves.map(l => {
    const data = l.data || {};
    // Merge meta into main object for easier access
    const merged = { ...data };
    if (data.meta) {
      Object.assign(merged, data.meta);
    }
    // Ensure we have the fields we need
    merged.setting = merged.setting || merged.name || "";
    merged.platform = merged.platform || "unknown";
    merged.stateType = merged.stateType || "unknown";
    merged.category = merged.category || "";
    merged.description = merged.description || "";
    merged.clicks = merged.clicks || 0;
    return merged;
  });
  
  // Apply platform filter (supports multiple selections)
  if (!currentPlatformFilter.includes('all') && currentPlatformFilter.length > 0) {
    rows = rows.filter(d => {
      const platform = (d.platform || "unknown").toLowerCase();
      return currentPlatformFilter.includes(platform);
    });
  }
  
  // Apply state type filter
  if (currentStateFilter !== 'all') {
    rows = rows.filter(d => {
      const stateType = (d.stateType || "unknown").toLowerCase();
      return stateType === currentStateFilter;
    });
  }
  
  // Apply search filter
  if (currentSearchQuery.trim()) {
    const query = currentSearchQuery.toLowerCase();
    rows = rows.filter(d => {
      const setting = (d.setting || "").toLowerCase();
      const description = (d.description || "").toLowerCase();
      const category = (d.category || "").toLowerCase();
      return setting.includes(query) || 
             description.includes(query) ||
             category.includes(query);
    });
  }
  
  return rows;
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
      children: settings.map(setting => {
        const w = setting.weight;
        const leafValue = typeof w === 'number' && w > 0 ? w : 1;
        return {
          name: setting.setting,
          meta: setting,
          value: leafValue,
          url: setting.url,
          description: setting.description,
          state: setting.state,
          stateType: setting.stateType,
          platform: setting.platform,
          category: setting.category
        };
      })
    };
    root.children.push(categoryNode);
  });
  
  currentRoot = d3.hierarchy(root)
    .sum(d => (d.children && d.children.length) ? 0 : (Number(d.value) || 1))
    .sort((a, b) => (b.value || 0) - (a.value || 0));
  
  if (currentCategoryFilter === 'all') {
    const leafCount = currentRoot.leaves ? currentRoot.leaves().length : 0;
    console.log('[Treemap All mode] filtered rows:', filtered.length, '| categories:', root.children.length, '| leaves:', leafCount, leafCount !== filtered.length ? ' (MISMATCH)' : '');
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
      // For leaf nodes, skip the setting name (it's shown as the title)
      // For categories, use category name
      if (!node.children || node.children.length === 0) {
        // Leaf node - skip setting name, it will be shown as the title
        // Don't add it to breadcrumb
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
 * Wrap SVG text to fit within maxWidth, with optional maxLines and lineHeight
 * Returns the number of pixels added beyond the first line
 */
function wrapSvgText(textSel, str, maxWidth, maxLines = 2, lineHeight = 24) {
  const words = (str || "").split(/\s+/).filter(Boolean);
  textSel.text(null);

  if (words.length === 0) {
    return 0;
  }

  let line = [];
  let lineNumber = 0;

  let tspan = textSel.append("tspan")
    .attr("x", textSel.attr("x"))
    .attr("dy", "0em");

  for (let i = 0; i < words.length; i++) {
    line.push(words[i]);
    tspan.text(line.join(" "));

    if (tspan.node().getComputedTextLength() > maxWidth && line.length > 1) {
      line.pop();
      tspan.text(line.join(" "));

      lineNumber++;
      if (lineNumber >= maxLines) {
        // clamp last line with ellipsis
        let clamped = line.join(" ");
        // Add remaining words that didn't fit
        for (let j = i; j < words.length; j++) {
          const testText = clamped + " " + words[j];
          tspan.text(testText);
          if (tspan.node().getComputedTextLength() > maxWidth) {
            break;
          }
          clamped = testText;
        }
        // Now trim characters until it fits with ellipsis
        while (tspan.node().getComputedTextLength() > maxWidth && clamped.length > 0) {
          clamped = clamped.slice(0, -1);
          tspan.text(clamped + "…");
        }
        return lineNumber * lineHeight; // pixels added beyond first line
      }

      line = [words[i]];
      tspan = textSel.append("tspan")
        .attr("x", textSel.attr("x"))
        .attr("dy", `${lineHeight}px`)
        .text(words[i]);
    }
  }

  return lineNumber * lineHeight;
}

/**
 * Render detail view card in SVG
 */
function renderDetailView(svg, width, height, payload, breadcrumb) {
  const padding = 14;
  const cornerRadius = 8;
  const headerHeight = 62; // Title + subtitle + spacing
  const footerHeight = 56; // Buttons + spacing
  const DETAIL_CARD_Y_OFFSET = 110; // Fixed upward offset for card position
  
  // Calculate card dimensions - make it smaller and more compact
  const cardWidth = Math.min(420, width * 0.60);
  // Ensure card height leaves room for buttons at the bottom
  const maxCardHeight = Math.min(380, height * 0.55);
  const cardHeight = maxCardHeight;
  
  // Center the card in the viewport, independent of click location
  const cardX = Math.max(
    20,
    Math.round((width - cardWidth) / 2)
  );

  // Center vertically and shift upward by fixed offset
  const cardY = Math.max(
    20,
    Math.round((height - cardHeight) / 2) - DETAIL_CARD_Y_OFFSET
  );
  
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
  
  // Title with wrapping
  const fullTitle = payload.name || "Setting";
  const titleX = cardX + padding;
  const titleY = cardY + padding + 18;
  
  const titleEl = card.append("text")
    .attr("x", titleX)
    .attr("y", titleY)
    .attr("font-size", "20px")
    .attr("font-weight", "600")
    .attr("fill", "#333");
  
  const titleExtra = wrapSvgText(titleEl, fullTitle, cardWidth - padding * 2, 2, 24);
  titleEl.append("title").text(fullTitle);
  
  // Breadcrumb/subtitle
  const subtitleY = titleY + 22 + titleExtra;
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
 * Update the treemap area callout text based on current sizing metric
 */
function updateTreemapAreaCallout() {
  const calloutEl = document.getElementById("treemapAreaCallout");
  if (!calloutEl) return;
  
  const metric = document.getElementById("sizingMetric")?.value || currentSizingMetric || "count";
  
  let explanation = "";
  switch (metric) {
    case "count":
      explanation = "Rectangle area represents the number of settings (each setting contributes 1).";
      break;
    case "actionable":
      explanation = "Rectangle area represents the number of actionable settings only.";
      break;
    case "risk-weighted":
      explanation = "Rectangle area represents a risk-weighted score (higher-risk settings contribute more area).";
      break;
    case "clicks":
      explanation = "Rectangle area represents the total clicks (or click depth) aggregated across settings.";
      break;
    default:
      explanation = "Rectangle area represents the current sizing metric.";
  }
  
  calloutEl.textContent = explanation;
}

/**
 * Get current treemap container dimensions (responsive to layout).
 */
function getTreemapSize() {
  const container = document.getElementById("treemapContainer");
  if (!container) return { width: 1200, height: 700 };
  const rect = container.getBoundingClientRect();
  return {
    width: Math.max(300, rect.width),
    height: Math.max(400, rect.height)
  };
}

/**
 * Render treemap visualization
 */
function renderTreemap() {
    // Update callout before rendering
    updateTreemapAreaCallout();
    
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
  
    const { width, height } = getTreemapSize();
    if (currentRoot && currentRoot.leaves) {
      console.log("Treemap size:", width, height, "| Leaf count:", currentRoot.leaves().length);
    }
  
    const svg = container.append("svg")
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("preserveAspectRatio", "xMidYMid meet");
  
    // Check if we should render detail view instead of treemap
    if (isDetailView && detailPayload) {
      renderDetailView(svg, width, height, detailPayload, detailBreadcrumb);
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
  
    // Get unique platforms for legend
    const platforms = Array.from(new Set(allData.map(d => d.platform))).sort();
  
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
      .attr("stroke-dasharray", "none")
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
      return !isCategory && isLeaf && w > 110 && h > 45;
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
        const maxChars = Math.floor(w / 7);
        if (name.length > maxChars && maxChars > 3) {
          return name.substring(0, maxChars - 3) + "...";
        }
        return name;
      });
  
    // Tooltip handlers removed - replaced with area evidence panel on category hover
  
    updateBreadcrumbs();
    renderLegend(platforms);
    renderBelowTreemapCharts();
  }
  

/**
 * Render legend showing platforms (with colors)
 */
function renderLegend(platforms) {
  const legendContainer = d3.select("#treemapLegend");
  legendContainer.selectAll("*").remove();
  
  // Create legend wrapper (styling via CSS for hotbar layout)
  const legend = legendContainer.append("div")
    .attr("class", "legend-wrapper");
  
  // Platforms section (with colors)
  const platformsSection = legend.append("div")
    .attr("class", "legend-section platforms-section");
  
  platformsSection.append("div")
    .attr("class", "legend-title")
    .text("Platforms (colors)");
  
  const platformsList = platformsSection.append("div")
    .attr("class", "legend-items");
  
  platforms.forEach(platform => {
    const item = platformsList.append("div")
      .attr("class", "legend-item");
    
    item.append("div")
      .attr("class", "legend-color")
      .style("background", PLATFORM_COLORS[platform] || PLATFORM_COLORS.unknown);
    
    item.append("span")
      .text(platform.charAt(0).toUpperCase() + platform.slice(1));
  });
}

/**
 * Render charts below treemap (stacked bar and pie chart)
 */
function renderBelowTreemapCharts() {
  const viewData = getCurrentViewLeafData();
  renderStackedPlatformChart(viewData);
  renderAreaSharePieChart(viewData);
}

/**
 * Calculate contribution value for a row based on current sizing metric
 */
function calculateContribution(row) {
  const metric = currentSizingMetric;
  
  if (metric === 'count') {
    return 1;
  } else if (metric === 'actionable') {
    const stateType = (row.stateType || "unknown").toLowerCase();
    return stateType === 'actionable' ? 1 : 0;
  } else if (metric === 'risk-weighted') {
    // Check if risk is numeric
    let risk = row.risk;
    if (typeof risk === 'number') {
      return risk;
    }
    // If risk is string, map it
    if (typeof risk === 'string') {
      const riskLower = risk.toLowerCase();
      if (riskLower.includes('high')) return 3;
      if (riskLower.includes('medium')) return 2;
      if (riskLower.includes('low')) return 1;
    }
    // Fallback: use category-based risk (same as calculateWeight)
    const category = (row.category || "").toLowerCase();
    if (category.includes('tracking')) return 2;
    if (category.includes('security')) return 1.5;
    return 1;
  } else if (metric === 'clicks') {
    const clicks = row.clicks || 0;
    return clicks > 0 ? clicks : 1;
  }
  return 1;
}

/**
 * Render area share pie chart based on current view and sizing metric
 */
function renderAreaSharePieChart(viewData) {
  const container = d3.select("#pieAreaChart");
  container.selectAll("*").remove();

  if (!viewData || viewData.length === 0) {
    container.append("p")
      .style("padding", "20px")
      .style("color", "#666")
      .style("text-align", "center")
      .text("No data available after filtering.");
    return;
  }

  // Aggregate contributions by platform
  const platformMap = new Map();
  
  viewData.forEach(row => {
    const platform = (row.platform || row.meta?.platform || "unknown").toLowerCase();
    const contribution = calculateContribution(row);
    
    if (!platformMap.has(platform)) {
      platformMap.set(platform, 0);
    }
    platformMap.set(platform, platformMap.get(platform) + contribution);
  });

  // Convert to array and sort by value descending
  const pieData = Array.from(platformMap.entries())
    .map(([platform, value]) => ({
      platform: platform,
      value: value
    }))
    .filter(d => d.value > 0)
    .sort((a, b) => b.value - a.value);

  if (pieData.length === 0) {
    container.append("p")
      .style("padding", "20px")
      .style("color", "#666")
      .style("text-align", "center")
      .text("No data available after filtering.");
    return;
  }

  // Calculate total for percentages
  const total = d3.sum(pieData, d => d.value);

  // Set up dimensions (height sized to fit pie + offset + legend rows)
  const containerWidth = container.node().getBoundingClientRect().width || 480;
  const width = containerWidth;
  const height = 400;
  const radius = Math.min(width, 320) / 2 - 20; // cap pie size so legend fits below

  // Create SVG
  const svg = container.append("svg")
    .attr("width", width)
    .attr("height", height);

  const pieOffsetY = 28; // move pie and labels down
  const g = svg.append("g")
    .attr("transform", `translate(${width / 2}, ${height / 2 + pieOffsetY})`);

  // Create pie generator
  const pie = d3.pie()
    .value(d => d.value)
    .sort(null);

  // Create arc generator
  const arc = d3.arc()
    .innerRadius(0)
    .outerRadius(radius);

  // Create arc for labels
  const labelArc = d3.arc()
    .innerRadius(radius + 20)
    .outerRadius(radius + 20);

  // Generate arcs
  const arcs = g.selectAll(".arc")
    .data(pie(pieData))
    .enter()
    .append("g")
    .attr("class", "arc");

  // Draw slices
  arcs.append("path")
    .attr("d", arc)
    .attr("fill", d => {
      const platform = d.data.platform;
      return PLATFORM_COLORS[platform] || PLATFORM_COLORS.unknown;
    })
    .attr("stroke", "#fff")
    .attr("stroke-width", 2)
    .on("mouseover", function(event, d) {
      d3.select(this)
        .attr("stroke-width", 3)
        .attr("opacity", 0.8);
    })
    .on("mouseout", function() {
      d3.select(this)
        .attr("stroke-width", 2)
        .attr("opacity", 1);
    });

  // Add percentage labels on slices (only if slice is large enough)
  arcs.filter(d => (d.endAngle - d.startAngle) > 0.1)
    .append("text")
    .attr("transform", d => `translate(${labelArc.centroid(d)})`)
    .attr("text-anchor", "middle")
    .attr("font-size", "11px")
    .attr("fill", "#333")
    .attr("font-weight", "600")
    .text(d => {
      const percent = ((d.value / total) * 100).toFixed(1);
      return percent >= 5 ? percent + "%" : "";
    });
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
    const platform = (d.platform || "unknown").toLowerCase();
    if (!platformMap.has(platform)) {
      platformMap.set(platform, {
        platform: platform,
        actionable: 0,
        navigational: 0,
        unknown: 0
      });
    }
    const counts = platformMap.get(platform);
    const stateType = (d.stateType || "unknown").toLowerCase();
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
  const height = 425;
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

  // Legend in chart panel (HTML, below the chart container)
  const panel = d3.select(container.node().parentNode);
  panel.selectAll(".stacked-chart-legend").remove();
  const legendDiv = panel.append("div").attr("class", "stacked-chart-legend");
  stackKeys.forEach(key => {
    const item = legendDiv.append("div").attr("class", "stacked-chart-legend-item");
    item.append("span").attr("class", "stacked-chart-legend-color").style("background-color", colorScale(key));
    item.append("span").attr("class", "stacked-chart-legend-label").text(key.charAt(0).toUpperCase() + key.slice(1));
  });
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
 * Clone a d3.hierarchy node into a plain object tree (so it can be re-passed to d3.hierarchy).
 * Preserves leaf metadata and ensures leaf value is numeric for layout.
 */
function cloneSubtree(hNode) {
  const isLeaf = !hNode.children || hNode.children.length === 0;
  if (isLeaf) {
    const val = hNode.value != null ? hNode.value : (hNode.data.value != null ? hNode.data.value : 1);
    return {
      ...hNode.data,
      name: hNode.data.name != null ? hNode.data.name : 'Setting',
      value: typeof val === 'number' && val > 0 ? val : 1
    };
  }
  return {
    name: hNode.data.name != null ? hNode.data.name : 'Category',
    children: hNode.children.map(cloneSubtree)
  };
}

/**
 * Zoom into a node
 */
function zoomInto(d) {
  if (d.depth === 0) {
    return;
  }
  if (isDetailView) {
    exitDetailView();
  }
  if (currentRoot) {
    zoomStack.push({ root: currentRoot, name: d.data.name });
  }
  const cloned = cloneSubtree(d);
  currentRoot = d3.hierarchy(cloned)
    .sum(x => (x.children && x.children.length) ? 0 : (Number(x.value) || 1))
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
 * Update the dropdown label text based on current selections
 */
function updatePlatformFilterLabel() {
  const trigger = document.getElementById("platformFilterTrigger");
  const label = trigger?.querySelector(".dropdown-label");
  if (!label) return;
  
  const selected = currentPlatformFilter.filter(p => p !== 'all');
  const allPlatforms = Array.from(new Set(allData.map(d => d.platform)))
    .filter(p => p && p !== 'unknown')
    .sort();
  
  if (currentPlatformFilter.includes('all') || selected.length === 0 || selected.length === allPlatforms.length) {
    label.textContent = "All platforms";
  } else if (selected.length === 1) {
    const platformName = selected[0].charAt(0).toUpperCase() + selected[0].slice(1);
    label.textContent = platformName;
  } else if (selected.length <= 3) {
    label.textContent = selected.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(", ");
  } else {
    label.textContent = `${selected.length} selected`;
  }
}

/**
 * Populate platform filter dropdown with unique platforms from data
 */
function populatePlatformFilter() {
  const dropdown = document.getElementById("platformFilterDropdown");
  const list = document.getElementById("platformFilterList");
  if (!dropdown || !list) {
    console.warn("platformFilterDropdown element not found");
    return;
  }
  
  // Get unique platforms and sort them
  const platforms = Array.from(new Set(allData.map(d => d.platform)))
    .filter(p => p && p !== 'unknown')
    .sort();
  
  // Clear existing items
  list.innerHTML = '';
  
  // Add "All" option
  const allItem = document.createElement("li");
  const allCheckbox = document.createElement("input");
  allCheckbox.type = "checkbox";
  allCheckbox.id = "platform-all";
  allCheckbox.value = "all";
  allCheckbox.checked = currentPlatformFilter.includes('all') || currentPlatformFilter.length === 0;
  
  const allLabel = document.createElement("label");
  allLabel.htmlFor = "platform-all";
  allLabel.textContent = "All";
  
  allItem.className = "dropdown-item";
  allItem.appendChild(allCheckbox);
  allItem.appendChild(allLabel);
  list.appendChild(allItem);
  
  // Add platform options
  platforms.forEach(platform => {
    const item = document.createElement("li");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = `platform-${platform}`;
    checkbox.value = platform;
    checkbox.checked = currentPlatformFilter.includes(platform);
    
    const label = document.createElement("label");
    label.htmlFor = `platform-${platform}`;
    label.textContent = platform.charAt(0).toUpperCase() + platform.slice(1);
    
    item.className = "dropdown-item";
    item.appendChild(checkbox);
    item.appendChild(label);
    list.appendChild(item);
  });
  
  // Update label
  updatePlatformFilterLabel();
}

/**
 * Populate category filter dropdown with unique categories from data
 */
function populateCategoryFilter() {
  const select = document.getElementById("categoryFilter");
  if (!select) return;
  const categories = getSortedCategories();
  const value = select.value;
  select.innerHTML = '';
  const allOpt = document.createElement("option");
  allOpt.value = 'all';
  allOpt.textContent = 'All categories';
  select.appendChild(allOpt);
  categories.forEach(cat => {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = (cat || 'unknown').replace(/_/g, ' ');
    select.appendChild(opt);
  });
  const guidedOpt = document.createElement("option");
  guidedOpt.value = 'guided';
  guidedOpt.textContent = 'Guided (one at a time)';
  select.appendChild(guidedOpt);
  if (value && Array.from(select.options).some(o => o.value === value)) {
    select.value = value;
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
  
  // Category intro (tutorial + definitions): collapsible, state persisted in localStorage
  const introBody = document.getElementById("categoryIntroBody");
  const toggleBtn = document.getElementById("toggleCategoryIntro");
  const INTRO_KEY = "category_intro_collapsed";

  function setIntroCollapsed(collapsed) {
    if (!introBody) return;
    introBody.classList.toggle("hidden", collapsed);
    if (toggleBtn) toggleBtn.textContent = collapsed ? "Show guide" : "Hide guide";
  }

  const introCollapsed = localStorage.getItem(INTRO_KEY) === "1";
  setIntroCollapsed(introCollapsed);

  if (toggleBtn) {
    toggleBtn.addEventListener("click", function() {
      const isCollapsed = !introBody.classList.contains("hidden");
      localStorage.setItem(INTRO_KEY, isCollapsed ? "1" : "0");
      setIntroCollapsed(isCollapsed);
    });
  }

  // Initialize callout
  updateTreemapAreaCallout();
  
  // Initialize platform filter dropdown label
  updatePlatformFilterLabel();
  
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
  // Setup custom platform filter dropdown
  const platformFilterDropdown = document.getElementById("platformFilterDropdown");
  const platformFilterTrigger = document.getElementById("platformFilterTrigger");
  const platformFilterMenu = document.getElementById("platformFilterMenu");
  const platformFilterList = document.getElementById("platformFilterList");
  
  if (platformFilterDropdown && platformFilterTrigger && platformFilterMenu && platformFilterList) {
    // Toggle dropdown on trigger click
    platformFilterTrigger.addEventListener("click", function(e) {
      e.stopPropagation();
      const isOpen = platformFilterMenu.classList.contains("open");
      if (isOpen) {
        platformFilterMenu.classList.remove("open");
        platformFilterTrigger.classList.remove("active");
      } else {
        platformFilterMenu.classList.add("open");
        platformFilterTrigger.classList.add("active");
      }
    });
    
    // Close dropdown when clicking outside
    document.addEventListener("click", function(e) {
      if (!platformFilterDropdown.contains(e.target)) {
        platformFilterMenu.classList.remove("open");
        platformFilterTrigger.classList.remove("active");
      }
    });
    
    // Handle checkbox changes
    platformFilterList.addEventListener("change", function(e) {
      if (e.target.type !== "checkbox") return;
      
      const allCheckbox = document.getElementById("platform-all");
      const checkboxes = platformFilterList.querySelectorAll('input[type="checkbox"]');
      const platformCheckboxes = Array.from(checkboxes).filter(cb => cb.value !== 'all');
      
      // Handle "All" option logic
      if (e.target.value === 'all') {
        if (e.target.checked) {
          // Select all platforms when "All" is checked
          platformCheckboxes.forEach(cb => cb.checked = true);
          currentPlatformFilter = ['all'];
        } else {
          // Prevent unchecking "All" directly - user must select specific platforms
          e.target.checked = true;
          return;
        }
      } else {
        // Platform checkbox changed
        const selectedPlatforms = platformCheckboxes
          .filter(cb => cb.checked)
          .map(cb => cb.value);
        
        if (e.target.checked) {
          // Uncheck "All" when a specific platform is selected
          if (allCheckbox) {
            allCheckbox.checked = false;
          }
          currentPlatformFilter = selectedPlatforms;
        } else {
          // Platform unchecked
          if (selectedPlatforms.length === 0) {
            // No platforms selected - select "All"
            if (allCheckbox) {
              allCheckbox.checked = true;
            }
            platformCheckboxes.forEach(cb => cb.checked = false);
            currentPlatformFilter = ['all'];
          } else {
            currentPlatformFilter = selectedPlatforms;
          }
        }
      }
      
      // Update label
      updatePlatformFilterLabel();
      
      // Update treemap and charts
      currentRoot = null;
      zoomStack = [];
      buildHierarchy();
      renderTreemap();
    });
  } else {
    console.warn("platformFilterDropdown elements not found");
  }
  
  const categoryFilterSelect = document.getElementById("categoryFilter");
  const guidedCategoryControls = document.getElementById("guidedCategoryControls");
  const showPrevCategoryBtn = document.getElementById("showPrevCategory");
  const showNextCategoryBtn = document.getElementById("showNextCategory");
  const resetGuidedCategoriesBtn = document.getElementById("resetGuidedCategories");
  
  if (categoryFilterSelect) {
    categoryFilterSelect.addEventListener("change", function() {
      currentCategoryFilter = this.value;
      guidedMode = (currentCategoryFilter === 'guided');
      if (currentCategoryFilter === 'guided') {
        const categories = getSortedCategories();
        revealedCategories = new Set(categories.length > 0 ? [categories[0]] : []);
        if (guidedCategoryControls) {
          guidedCategoryControls.classList.remove("hidden");
        }
      } else {
        revealedCategories.clear();
        if (guidedCategoryControls) {
          guidedCategoryControls.classList.add("hidden");
        }
      }
      currentRoot = null;
      zoomStack = [];
      buildHierarchy();
      renderTreemap();
    });
  }
  
  if (showNextCategoryBtn) {
    showNextCategoryBtn.addEventListener("click", function() {
      if (currentCategoryFilter !== 'guided') return;
      const categories = getSortedCategories();
      const next = categories.find(c => !revealedCategories.has(c));
      if (next) {
        revealedCategories.add(next);
        currentRoot = null;
        zoomStack = [];
        buildHierarchy();
        renderTreemap();
      }
    });
  }
  
  if (showPrevCategoryBtn) {
    showPrevCategoryBtn.addEventListener("click", function() {
      if (currentCategoryFilter !== 'guided') return;
      const categories = getSortedCategories();
      const revealedOrdered = categories.filter(c => revealedCategories.has(c));
      if (revealedOrdered.length <= 1) return; // keep at least the first
      revealedOrdered.pop();
      revealedCategories = new Set(revealedOrdered);
      currentRoot = null;
      zoomStack = [];
      buildHierarchy();
      renderTreemap();
    });
  }
  
  if (resetGuidedCategoriesBtn) {
    resetGuidedCategoriesBtn.addEventListener("click", function() {
      if (currentCategoryFilter !== 'guided') return;
      const categories = getSortedCategories();
      revealedCategories = new Set(categories.length > 0 ? [categories[0]] : []);
      currentRoot = null;
      zoomStack = [];
      buildHierarchy();
      renderTreemap();
    });
  }
  
  if (sizingMetricSelect) {
    sizingMetricSelect.addEventListener("change", function() {
      currentSizingMetric = this.value;
      updateTreemapAreaCallout();
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
  
  // Debounced resize: recompute treemap with current container dimensions
  let resizeTimeout;
  window.addEventListener("resize", function() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(function() {
      renderTreemap();
    }, 150);
  });
}

// Setup event handlers when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupEventHandlers);
} else {
  // DOM is already ready
  setupEventHandlers();
}