import json
from pathlib import Path
import os
import urllib.parse


# -----------------------------
# Utilities
# -----------------------------
def load_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def basename(path_str: str) -> str:
    return os.path.basename(path_str.replace("\\", "/"))


def normalize_url(url: str) -> str:
    """
    Normalize URL for matching:
    - remove query / fragment
    - strip trailing slash
    """
    parsed = urllib.parse.urlsplit(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return clean.rstrip("/")


# -----------------------------
# Platform normalization
# -----------------------------
def normalize_platform(platform: str) -> str:
    """
    Normalize platform names to match crawl_results filenames.
    """
    p = platform.lower()

    PLATFORM_ALIASES = {
        "twitterx": "x",
        "twitter": "x",
        "x": "x",
        "facebook": "facebook",
        "linkedin": "linkedin",
        "google": "google",
        "instagram": "instagram",
        "reddit": "reddit",
    }

    return PLATFORM_ALIASES.get(p, p)


# -----------------------------
# URL recovery from filename
# -----------------------------
def url_from_image_path(image_path: str) -> str | None:
    """
    Recover URL embedded in screenshot filename.

    Handles:
      - trailing '_' before .png
      - ___ → ://
      - _ → /
    """
    fname = basename(image_path)

    base = fname[:-4] if fname.lower().endswith(".png") else fname
    base = base.rstrip("_")

    if "http" not in base:
        return None

    _, url_part = base.split("http", 1)
    url_part = "http" + url_part

    url_part = url_part.replace("___", "://")
    url_part = url_part.replace("_", "/")

    return urllib.parse.unquote(url_part)


# -----------------------------
# Generalized path variants
# -----------------------------
def normalize_path_variants(url: str) -> list[str]:
    """
    Generate multiple canonical URL variants to match crawler URLs.

    Handles:
    - slash vs underscore inside path segments
    - collapsing only trailing segments (correct for settings pages)
    """
    parsed = urllib.parse.urlsplit(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]

    variants = set()

    # 1. original path
    variants.add("/" + "/".join(parts))

    # 2. collapse trailing segments progressively
    #    e.g. settings / connected / accounts
    #    -> settings / connected_accounts
    for i in range(1, len(parts)):
        collapsed = parts[:i] + ["_".join(parts[i:])]
        variants.add("/" + "/".join(collapsed))

    # 3. fully collapsed (optional but safe)
    variants.add("/" + "_".join(parts))

    return [
        f"{parsed.scheme}://{parsed.netloc}{path}"
        for path in variants
    ]

# -----------------------------
# Crawl results helpers
# -----------------------------
def build_platform_layer_lookup(crawl_file: Path) -> dict:
    """
    Build normalized_url -> layer_number
    from ONE crawl_results.json file.
    """
    lookup = {}
    data = load_json(crawl_file)

    for layer_name, urls in data.get("layer_dict", {}).items():
        if not layer_name.startswith("Layer"):
            continue

        layer_num = int(layer_name.split()[-1])

        for url in urls:
            lookup[normalize_url(url)] = layer_num

    return lookup


def find_crawl_file(platform: str, click_counts_dir: Path) -> Path | None:
    """
    Find the crawl_results.json file for a platform using
    substring matching on lowercase names.
    """
    for p in click_counts_dir.glob("*_crawl_results.json"):
        if platform in p.name.lower():
            return p
    return None


# -----------------------------
# MAIN
# -----------------------------
def main():
    text_extractions_path = Path("../screenshot-classifier/extracted_settings.json")
    click_counts_dir = Path("../gemini-team/picasso/click_counts")
    output_path = Path("data/extracted_settings_with_urls_and_layers.json")

    data = load_json(text_extractions_path)

    url_added = 0
    layer_matched = 0
    layer_missing = 0

    for block in data:
        raw_platform = block.get("platform", "")
        platform = normalize_platform(raw_platform)

        crawl_file = find_crawl_file(platform, click_counts_dir)

        if crawl_file:
            layer_lookup = build_platform_layer_lookup(crawl_file)
        else:
            print(f"[WARN] No crawl file for platform '{raw_platform}' → '{platform}'")
            layer_lookup = {}

        for setting in block.get("all_settings", []):
            # ---- URL recovery ----
            if not setting.get("url"):
                image_path = setting.get("image_path")
                if image_path:
                    setting["url"] = url_from_image_path(image_path)
                    url_added += 1

            # ---- Layer annotation ----
            url = setting.get("url")
            layer = None

            if url:
                norm = normalize_url(url)
                for candidate in normalize_path_variants(norm):
                    if candidate in layer_lookup:
                        layer = layer_lookup[candidate]
                        break

            setting["layer"] = layer

            if layer is not None:
                layer_matched += 1
            else:
                layer_missing += 1

    save_json(output_path, data)

    print("[DONE]")
    print(f"  URLs added:    {url_added}")
    print(f"  Layers found:  {layer_matched}")
    print(f"  Layers null:   {layer_missing}")
    print(f"[OUTPUT] {output_path.resolve()}")


if __name__ == "__main__":
    main()
