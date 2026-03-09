import { refreshTreemap } from "./treemap.js";

function loadTreemap() {
    return;
}
function loadAdditional() {
    return;
}

const treemap = document.getElementById("treemapContainer");
const additional = document.getElementById("additional");

document.getElementById('recommendationsBtn').addEventListener('click', function() {
    if (additional) { additional.classList.add('hidden'); }
    if (treemap) {
        treemap.classList.remove('hidden');
        refreshTreemap();
    }
});

document.getElementById('crossPlatformBtn').addEventListener('click', function() {  
    if (treemap) {treemap.classList.add('hidden')};
    if (additional) {additional.classList.remove('hidden')};
});

// Draggable sidebar edge (Explore page)
(function initDraggableSidebar() {
    const sidebar = document.querySelector(".sidebar");
    if (!sidebar) return;

    const KEY = "pad_sidebar_width";
    const MIN_WIDTH = 10; // keep a thin rail so it can be re-expanded
    const MAX_WIDTH = 360;

    // Apply stored width if available
    const stored = parseInt(localStorage.getItem(KEY), 10);
    let initialWidth = !Number.isNaN(stored) && stored >= MIN_WIDTH && stored <= MAX_WIDTH
        ? stored
        : 250;

    sidebar.style.width = initialWidth + "px";
    sidebar.style.flex = `0 0 ${initialWidth}px`;
    if (initialWidth <= MIN_WIDTH + 1) {
        sidebar.classList.add("sidebar-collapsed");
    }

    // Create a thin draggable edge on the right side of the sidebar
    let resizer = sidebar.querySelector(".sidebar-resizer");
    if (!resizer) {
        resizer = document.createElement("div");
        resizer.className = "sidebar-resizer";
        sidebar.appendChild(resizer);
    }

    let isDragging = false;
    let startX = 0;
    let startWidth = 0;

    function onMouseMove(event) {
        if (!isDragging) return;
        const dx = event.clientX - startX;
        let newWidth = startWidth + dx;
        if (newWidth < MIN_WIDTH) newWidth = MIN_WIDTH;
        if (newWidth > MAX_WIDTH) newWidth = MAX_WIDTH;

        sidebar.style.width = newWidth + "px";
        sidebar.style.flex = `0 0 ${newWidth}px`;

        if (newWidth <= MIN_WIDTH + 1) {
            sidebar.classList.add("sidebar-collapsed");
        } else {
            sidebar.classList.remove("sidebar-collapsed");
        }
    }

    function onMouseUp() {
        if (!isDragging) return;
        isDragging = false;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);

        const width = parseInt(sidebar.getBoundingClientRect().width, 10);
        if (!Number.isNaN(width)) {
            localStorage.setItem(KEY, String(width));
        }
    }

    resizer.addEventListener("mousedown", function (event) {
        event.preventDefault();
        isDragging = true;
        startX = event.clientX;
        startWidth = sidebar.getBoundingClientRect().width;

        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
    });
})();