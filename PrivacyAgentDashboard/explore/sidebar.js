function loadTreemap() {
    return;
}
function loadAdditional() {
    return;
}

document.getElementById('recommendationsBtn').addEventListener('click', function() {
    const additional = document.getElementById("additional");
    const categoryIntro = document.getElementById("categoryIntro");
    const treemap = document.getElementById("treemap");
    
    // Hide additional section
    if (additional) {
        additional.classList.add('hidden');
    }
    
    // Show category intro and treemap if they exist
    if (categoryIntro) {
        categoryIntro.classList.remove('hidden');
    }
    if (treemap) {
        treemap.classList.remove('hidden');
    }
});

document.getElementById('crossPlatformBtn').addEventListener('click', function() {
    const tutorial = document.getElementById("categoryIntro");
    const treemap = document.getElementById("treemap");
    const additional = document.getElementById("additional");
    
    // Hide category intro and treemap
    if (tutorial) {
        tutorial.classList.add('hidden');
    }
    if (treemap) {
        treemap.classList.add('hidden');
    }
    
    // Show additional section if it exists
    if (additional) {
        additional.classList.remove('hidden');
    }
});