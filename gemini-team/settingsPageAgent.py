from playwright.sync_api import sync_playwright
from urllib.parse import urljoin, urlparse
import re
import os
from google import genai
from google.genai import types
from google.genai.types import Content, Part
import json
import time


def is_valid_link(href, text, role):
    """
    Uses Google Gemini to determine if a link leads to settings toggles.
    
    Args:
        href: The URL of the link (absolute)
        text: The visible text of the link
        role: The role of the link
    
    Returns:
        dict: {"has_settings_toggles": "yes" or "no"}
        Returns {"has_settings_toggles": "no"} on error
    """
    API_KEY = "AIzaSyCQHcHyvx5zY0uTDbl4IH33ajUzt2CdI0I" # os.environ.get("GEMINI_API_KEY")
    if not API_KEY:
        print("Error: GEMINI_API_KEY not set.")
        raise ValueError("Missing Gemini API key.")

    client = genai.Client(api_key=API_KEY)

    context = f"Link URL: {href}, Link Text: {text}, Link Role: {role}"

    prompt = (
        f"Analyze this link from a privacy/settings page:\n\n{context}\n\n"
        "Platforms often nest their setting toggles within nested links. The goal of this program is to find all " 
        f"the user configurable setting toggles by crawling through the different links on LinkedIn's settings page. "
        "Please determine if clicking this link will lead to a page that contains privacy/data/security SETTINGS TOGGLES or CONTROLS that users can enable/disable.\n\n"
        "Links that lead to settings toggles include:\n"
        "- /settings or /account\n"
        "- /preferences or /config\n"
        "- /admin or /profile\n"
        "- /setup or /options\n"
        "- Always verify that the main domain name is spelled correctly\n"
        "Links that DO NOT lead to settings toggles include:\n"
        "- Information/help pages (even if about privacy)\n"
        "- Policy pages\n"
        "- FAQ pages\n"
        "- Blog posts or articles\n"
        "- Privacy/settings pages in languages other than English\n"
        "Return ONLY valid JSON in this exact format:\n"
        '{"has_settings_toggles": "yes"}\n'
        'or\n'
        '{"has_settings_toggles": "no"}\n\n'
        "Do not include any other text, explanations, or markdown formatting. The page should strictly be related to LinkedIn."
    )

    config = types.GenerateContentConfig(
        temperature = 0.2,
        # max_output_tokens = 512
    )

    ###
    try:
        resp = client.models.generate_content(
            model = "gemini-2.5-pro",
            contents = [Content(role="user", parts=[Part(text=prompt)])],
            config = config
        )
        
        # Extract text from response? (not sure what this is doing)
        text = ""
        try:
            cands = getattr(resp, "candidates", None) or []
            if cands:
                first = cands[0]
                content = getattr(first, "content", None)
                parts = getattr(content, "parts", None) if content is not None else None
                if parts:
                    for part in parts:
                        if getattr(part, "text", None):
                            text += part.text
                else:
                    cand_text = getattr(first, "text", None)
                    if isinstance(cand_text, str):
                        text = cand_text
        except Exception as e:
            print(f"Error extracting response text: {e}")
            return {"has_settings_toggles": "no"}
        
        # Parse JSON from response
        # Clean up the text (remove markdown code blocks if present)
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        # Try to parse JSON
        try:
            result = json.loads(text)

            if isinstance(result, dict) and "has_settings_toggles" in result:
                return result
            else:
                # If JSON is valid but wrong format, default to no
                return {"has_settings_toggles": "no"}
        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract yes/no from text
            text_lower = text.lower()
            if '"has_settings_toggles": "yes"' in text_lower or '"has_settings_toggles":"yes"' in text_lower:
                return {"has_settings_toggles": "yes"}
            elif '"has_settings_toggles": "no"' in text_lower or '"has_settings_toggles":"no"' in text_lower:
                return {"has_settings_toggles": "no"}
            else:
                # Default to no if we can't parse
                print(f"Could not parse Gemini response: {text}")
                return {"has_settings_toggles": "no"}
                
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return {"has_settings_toggles": "no"}
    
    ###


def sanitize_filename(text):
    """Remove invalid filename characters"""
    if not text:
        return "unnamed"
    # Remove invalid chars and limit length
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(text))
    return safe[:150] or "unnamed"


def crawl_settings(url):
    with sync_playwright() as p:
        
        # Try to load existing storage state (cookies) for authentication
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        STATE_DIR = os.path.join(BASE_DIR, "profiles", "storage")
        host = urlparse(url).hostname # changed
        state_path = os.path.join(STATE_DIR, f"{host}.json")
        
        browser = p.chromium.launch(headless=False)
        # page = browser.new_page() i wrote this

        # Load storage state if it exists (contains saved cookies/login session)
        if os.path.exists(state_path):
            context = browser.new_context(
                storage_state=state_path, # changed
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            print(f"[INFO] Loaded storage state for {host} → {state_path}")
        else:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            print(f"[INFO] No storage state found for {host}. Starting without authentication.")
        
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded")
        
        # Wait 1 minute for user to log in and navigate
        print(f"\n{'='*60}")
        print("Browser opened! Please:")
        print("1. Log in to your account")
        print("2. Navigate to the settings page you want to crawl")
        print(f"\nCrawling will start in 60 seconds...")
        print(f"{'='*60}\n")

        time.sleep(60)
        page.wait_for_timeout(2000) # wait a moment for page to settle

        # while loop + stack data structure to store the links
        # stops when the stack is empty
        # depth first search essentially

        a_tags = page.locator("a").all()  # in order for this to work, we need to do one nav li at a time
        link_queue = []  # Each item: (url, text, role, depth)
        visited_links = set()

        layer_dict = {}  # Maps "Layer N" -> [list of URLs at that depth]

        # Initialize Layer 0 with starting page links
        layer_dict["Layer 0"] = [] # mechanism to store the links at each layer (genius)

        for a_tag in a_tags:
            try:
                href = a_tag.get_attribute("href")
                
                absolute_url = urljoin(page.url, href)
                parsed = urlparse(absolute_url)
                normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                text = (a_tag.inner_text() or "").strip()
                role = a_tag.get_attribute("role")
                
                # Add depth=0 for initial links
                link_queue.append((normalized, text, role, 0))
                layer_dict["Layer 0"].append(normalized)

            except Exception as e:
                print(f"Initial link array is empty: {e}")
                raise

        # Stopping condition: max iterations
        iteration_count = 0
        max_iterations = 5000

        while link_queue:
            iteration_count += 1
            if iteration_count > max_iterations:
                print(f"[INFO] Reached maximum iterations ({max_iterations}). Stopping crawl.")
                break

            href, text, role, depth = link_queue.pop(0)  # Now includes depth

            result = is_valid_link(href=href, text=text, role=role)
            time.sleep(1)  # don't want to hit quota for gemini calls

            print(f"Visiting (depth {depth}): {text} -> {href}, Result: {result}")

            if (href in visited_links) or (result["has_settings_toggles"] == "no"):
                visited_links.add(href)
                continue

            # Everything below here is SKIPPED if the if statement is True:
            visited_links.add(href)

            try:
                page.goto(href, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)

                a_tags = page.locator("a").all()

                safe_filename = sanitize_filename(f"{text}_{href}")
                screenshot_path = f"picasso/{safe_filename}.png"

                page.screenshot(path=screenshot_path, full_page=True, timeout=120000)

                # Children are at depth + 1
                child_depth = depth + 1
                layer_key = f"Layer {child_depth}"
                
                # Create the layer if it doesn't exist
                if layer_key not in layer_dict:
                    layer_dict[layer_key] = []

                for a_tag in a_tags:
                    try:
                        new_href = a_tag.get_attribute("href")

                        if not new_href:
                            continue
                        
                        absolute_url = urljoin(page.url, new_href)
                        parsed = urlparse(absolute_url)
                        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        
                        if normalized not in visited_links:
                            new_text = (a_tag.inner_text() or "").strip()
                            new_role = a_tag.get_attribute("role")
                            
                            # Add with child_depth
                            link_queue.append((normalized, new_text, new_role, child_depth))
                            layer_dict[layer_key].append(normalized)
                    
                    except Exception as e:
                        continue

            except Exception as e:
                print(f"Error visiting {href}: {e}")
                continue

        # Save results to JSON
        output_data = {
            "visited_links": list(visited_links),
            "layer_dict": layer_dict,  # {"Layer 0": [...], "Layer 1": [...], ...}
            "total_visited": len(visited_links),
            "total_layers": len(layer_dict),
            "links_per_layer": {k: len(v) for k, v in layer_dict.items()}
        }
        
        # Save to picasso folder with the hostname as the filename
        os.makedirs("picasso", exist_ok=True)
        output_path = f"picasso/{host}_crawl_results.json"
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        
        print(f"\n{'='*60}")
        print(f"✓ Crawl results saved to {output_path}")
        print(f"  Total links visited: {len(visited_links)}")
        print(f"  Total layers: {len(layer_dict)}")
        print(f"  Links per layer:")
        for layer_name, links in layer_dict.items():
            print(f"    {layer_name}: {len(links)} links")
        print(f"{'='*60}\n")

        browser.close()



        # html = page.content()

        # with open(f"page.html", "w", encoding="utf-8") as f:
        #     f.write(html)


        # # links = page.locator("a").all()
        # tabs = page.query_selector_all("nav ul li a")

        # for i, link in enumerate(tabs):
        #     try:
        #         # Get the href attribute
        #         href = link.get_attribute("href")
                
        #         # Get the visible text
        #         text = link.inner_text()
                
        #         # Get any other attribute
        #         role = link.get_attribute("role")
        #         aria_label = link.get_attribute("aria-label")
                
        #         print(f"Link {i}: href={href}, text={text}, role={role}")
        #     except Exception as e:
        #         print(f"Error: {e}")
        #         continue

        # # Find all sidebar items (this is a major assumption though)
        # tabs = page.query_selector_all("nav")

        # for i, tab in enumerate(tabs):
        #     tab_text = tab.inner_text()
        #     print(f"Visiting: {tab_text}")

            # if "Privacy topics" in tab_text:
            #     tab.click()
            #     page.wait_for_load_state("networkidle")

                # links = page.locator("a").all()

                # for i, link in enumerate(links):
                #     try:
                #         # Get the href attribute
                #         href = link.get_attribute("href")
                        
                #         # Get the visible text
                #         text = link.inner_text()
                        
                #         # Get any other attribute
                #         role = link.get_attribute("role")
                #         aria_label = link.get_attribute("aria-label")
                        
                #         print(f"Link {i}: href={href}, text={text}, role={role}")
                #     except Exception:
                #         continue
            
                # html = page.content()

                # with open(f"page.html", "w", encoding="utf-8") as f:
                #     f.write(html)

        # browser.close()


if __name__ == "__main__":
    url = 'https://www.linkedin.com/mypreferences/d/categories/account'
    crawl_settings(url)
    