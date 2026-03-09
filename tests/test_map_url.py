import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "database" / "map_url.py"

spec = importlib.util.spec_from_file_location("map_url", MODULE_PATH)
map_url = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(map_url)


def test_normalize_url_strips_query_fragment_and_trailing_slash():
    url = "https://example.com/settings/privacy/?q=1#section"
    assert map_url.normalize_url(url) == "https://example.com/settings/privacy"


def test_normalize_platform_aliases():
    assert map_url.normalize_platform("TwitterX") == "x"
    assert map_url.normalize_platform("twitter") == "x"
    assert map_url.normalize_platform("LinkedIn") == "linkedin"


def test_url_from_image_path_decodes_embedded_url():
    image = "../gemini-team/picasso/Spotify/Account privacy_https___www.spotify.com_us_account_privacy_.png"
    recovered = map_url.url_from_image_path(image)
    assert recovered == "https://www.spotify.com/us/account/privacy"


def test_url_from_image_path_returns_none_without_http():
    assert map_url.url_from_image_path("foo/bar/no_url_here.png") is None


def test_normalize_path_variants_generates_collapsed_paths():
    url = "https://x.com/settings/connected/accounts"
    variants = set(map_url.normalize_path_variants(url))
    assert "https://x.com/settings/connected/accounts" in variants
    assert "https://x.com/settings/connected_accounts" in variants
    assert "https://x.com/settings_connected_accounts" in variants


def test_build_platform_layer_lookup_reads_layer_dict(tmp_path: Path):
    payload = {
        "layer_dict": {
            "Layer 1": ["https://site.com/a?utm=1"],
            "Layer 2": ["https://site.com/b/"],
            "Ignored": ["https://site.com/ignored"],
        }
    }
    crawl_file = tmp_path / "sample_crawl_results.json"
    crawl_file.write_text(json.dumps(payload), encoding="utf-8")

    lookup = map_url.build_platform_layer_lookup(crawl_file)
    assert lookup["https://site.com/a"] == 1
    assert lookup["https://site.com/b"] == 2
    assert "https://site.com/ignored" not in lookup


def test_find_crawl_file_finds_platform_specific_file(tmp_path: Path):
    a = tmp_path / "x_crawl_results.json"
    b = tmp_path / "reddit_crawl_results.json"
    a.write_text("{}", encoding="utf-8")
    b.write_text("{}", encoding="utf-8")

    found = map_url.find_crawl_file("reddit", tmp_path)
    assert found is not None
    assert found.name == "reddit_crawl_results.json"
