function loadTreemap() {
    return;
}
function loadAdditional() {
    return;
}

document.getElementById('recommendationsBtn').addEventListener('click', function() {
    const categoryIntro = document.getElementById("categoryIntro");
    const treemapSection = document.getElementById("treemap");
    const treemap = document.getElementById("treemapContainer");
    const additional = document.getElementById("additional");
    
    if (additional) additional.classList.add('hidden');
    if (categoryIntro) categoryIntro.classList.remove('hidden');
    if (treemapSection) treemapSection.classList.remove('hidden');
    if (treemap) treemap.classList.remove('hidden');
});

document.getElementById('crossPlatformBtn').addEventListener('click', function() {
    const categoryIntro = document.getElementById("categoryIntro");
    const treemapSection = document.getElementById("treemap");
    const treemap = document.getElementById("treemapContainer");
    const additional = document.getElementById("additional");
    
    if (categoryIntro) categoryIntro.classList.add('hidden');
    if (treemapSection) treemapSection.classList.add('hidden');
    if (treemap) treemap.classList.add('hidden');
    if (additional) additional.classList.remove('hidden');
});