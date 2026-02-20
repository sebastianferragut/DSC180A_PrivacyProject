function loadTreemap() {
    return;
}
function loadAdditional() {
    return;
}

document.getElementById('recommendationsBtn').addEventListener('click', function() {
    const categoryIntro = document.getElementById("categoryIntro");
    const treemap = document.getElementById("treemapContainer");
    
    // Hide additional section
    if (additional) {
        additional.classList.add('hidden');
    }
    
    // Show category intro and treemap if they exist
    if (treemap) {
        treemap.classList.remove('hidden');
    }
});

document.getElementById('crossPlatformBtn').addEventListener('click', function() {
    const treemap = document.getElementById("treemapContainer");
    const additional = document.getElementById("additional");
    
    // Hide category intro and treemap
    if (treemap) {
        treemap.classList.add('hidden');
    }
    
    // Show additional section if it exists
    if (additional) {
        additional.classList.remove('hidden');
    }
});