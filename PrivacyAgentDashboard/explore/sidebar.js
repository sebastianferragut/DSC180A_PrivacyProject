function $$(selector, context = document) {
  return Array.from(context.querySelectorAll(selector));
}

// Sidebar behavior for the Explore dashboard.
// On pages where both the intro/treemap and charts live together
// (e.g., explore/index.html), the sidebar buttons act as view
// toggles instead of page navigators:
//
// - "Your recommendations"  -> show category-intro + treemap-section
// - "Cross-platform privacy" -> show only charts-section (pie + bar)
//
// On other pages that don't contain these sections, the links fall
// back to their normal navigation behavior.

const sidebar = document.querySelector('aside.sidebar');
if (sidebar) {
  const links = $$('a', sidebar);

  const categoryIntro = document.querySelector('.category-intro');
  const treemapSection = document.querySelector('.treemap-section');
  const chartsSection = document.querySelector('.charts-section');

  // We only do in-page toggling when all three sections exist.
  const canToggleViews = !!(categoryIntro && treemapSection && chartsSection);

  function setVisible(element, visible) {
    if (!element) return;
    element.style.display = visible ? '' : 'none';
  }

  function activateLink(targetLink) {
    for (const link of links) {
      if (link === targetLink) {
        link.classList.add('current');
      } else {
        link.classList.remove('current');
      }
    }
  }

  function showRecommendationsView(triggerLink) {
    activateLink(triggerLink);
    setVisible(categoryIntro, true);
    setVisible(treemapSection, true);
    setVisible(chartsSection, false);
  }

  function showCrossPlatformView(triggerLink) {
    activateLink(triggerLink);
    setVisible(categoryIntro, false);
    setVisible(treemapSection, false);
    setVisible(chartsSection, true);
  }

  // Always prevent navigation for these two buttons so we don't
  // leave the current directory; when the full set of sections
  // is present we use them purely as in-page view toggles.
  for (const link of links) {
    const title = link.textContent.trim();

    if (title === 'Your recommendations') {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        if (canToggleViews) {
          showRecommendationsView(link);
        }
      });
    } else if (title === 'Cross-platform privacy') {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        if (canToggleViews) {
          showCrossPlatformView(link);
        }
      });
    }
  }

  // Initial state: show recommendations by default if possible.
  if (canToggleViews) {
    const defaultLink = links.find(
      (l) => l.textContent.trim() === 'Your recommendations'
    );
    if (defaultLink) {
      showRecommendationsView(defaultLink);
    }
  }
}