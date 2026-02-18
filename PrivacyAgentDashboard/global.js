function $$(selector, context = document) {
  return Array.from(context.querySelectorAll(selector));
}

const ARE_WE_HOME = document.documentElement.classList.contains('home');
let pages = [
  { url: '', title: 'About'},
  { url: 'explore/', title: 'Explore'},
  { url: 'modify/', title: 'Modify'},
  { url: 'https://github.com/sebastianferragut/DSC180A_PrivacyProject', title: 'GitHub'}
];

let nav = document.getElementById('navbar');
for (let p of pages) {
  let url = p.url;
  let title = p.title;
  url = !ARE_WE_HOME && !url.startsWith('http') ? '../' + url : url;
  let a = document.createElement('a');
  a.href = url;
  a.textContent = title;
  nav.append(a);
  if (a.host === location.host && a.pathname === location.pathname) {
    a.classList.add('current');
  }
  if (a.href === "https://github.com/sebastianferragut/DSC180A_PrivacyProject") {
    a.target='_blank';
  }
}