function loadTreemap() {
    return;
}
function loadAdditional() {
    return;
}

// const categoryIntro = document.getElementById("categoryIntro");
const treemap = document.getElementById("treemapContainer");
const additional = document.getElementById("additional");

document.getElementById('recommendationsBtn').addEventListener('click', function() {
    if (additional) additional.classList.add('hidden');
    if (treemap) treemap.classList.remove('hidden');
});

document.getElementById('crossPlatformBtn').addEventListener('click', function() {  
    if (treemap) treemap.classList.add('hidden');
    if (additional) additional.classList.remove('hidden');
});