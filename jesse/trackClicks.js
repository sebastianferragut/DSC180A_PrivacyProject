const { chromium } = require('playwright');
const cheerio = require('cheerio');

(async () => {
  const browser = await chromium.launch({
    headless: false,
    channel: 'chrome',
    slowMo: 250, // slow down actions for visibility
    args: [
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
    ],
  });

  const context = await browser.newContext();
  const page = await context.newPage();
  let url = ""

  try {
    await page.goto('https://zoom.us', { waitUntil: 'domcontentloaded' });

    // Wait for and click 'Sign In' link
    await page.waitForSelector('text=Sign In', { timeout: 10000 });
    await page.click('a[href*="signin"]');

    // Wait for navigation to finish
    await page.waitForLoadState('domcontentloaded');

    // Example: verify you're on the sign-in page
    console.log('Now on sign-in page.');

    // Step 2: Pause and let the user sign in manually
    url = page.url();
    
    while (url.includes('/signin') || url.includes('/login') || url.includes('/signup')) {
        await page.waitForTimeout(6000);
        url = page.url();
    };
    console.log('Signed in!')

    // Step 3: Continue to profile page (now the hard part)
    console.log('Navigated to profile page.');

    
    // *** Recursive Search *** //
    const clickableTags = ['a', 'button', 'input', 'ul', 'li', 'aside'];

    function findPathByText($, root, searchText) {
      let resultPath = null;

      function traverse(node, path = []) {
        if (!node || resultPath) return;

        const nodeId = $(node).attr('id');
        const nodeText = ($(node).text() || "").trim();

        // only include this node in the path if it has both id and some visible text
        let newPath = [...path];
        if (nodeId && nodeText && clickableTags.includes(node.name)) { // && node.name !== 'div'
          newPath.push(nodeId);
        }

        // Check if this node matches
        if (nodeText === searchText) {
          resultPath = newPath;
          return;
        }

        // recurse into children
        $(node).children().each((_, child) => {
          traverse(child, newPath);
        });
      }

      traverse(root, []);
      return resultPath; // array of IDs along the path
    }

    // Usage
    const html = await page.content();
    const $ = cheerio.load(html);

    const path = findPathByText($, $.root(), "Data & Privacy");

    if (path) {
      console.log("Path of IDs to target:", path);
      console.log("Estimated clicks:", path.length);
    } else {
      console.log("Text not found");
    }


    // End of search //

    await browser.close();

  } catch (err) {
    console.error('Error during automation:', err);
  } finally {
    await browser.close();
  }
})();

// huangjesse1@gmail.com