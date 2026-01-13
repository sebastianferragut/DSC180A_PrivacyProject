import json
from pathlib import Path

SNAPSHOT_CANDIDATES = [
    # platform, query, expected_setting_id
    ("reddit", "follow", "allow_people_to_follow_you"),
    ("reddit", "search results", "show_up_in_search_results"),

    ("instagram", "private account", "private_account"),
    ("instagram", "tag you", "who_can_tag_you"),

    ("twitterX", "protect posts", "audience__media_and_tagging"),  # best we can do from snapshot (leaf not present)
    ("twitterX", "direct messages", "direct_messages"),

    ("googleaccount", "web app activity", "web___app_activity"),
    ("googleaccount", "ad center", "my_ad_center"),

    ("facebook", "change password", "change_password"),
    ("facebook", "two factor", "two_factor_authentication"),

    ("linkedin", "two factor", "two_factor_authentication"),
    ("linkedin", "ads off", "ads_off_linkedin"),

    ("spotify", "sign out everywhere", "sign_out_everywhere"),
    ("spotify", "close account", "close_account"),

    ("zoom", "automatic recording", "automatic_recording"),
    ("zoom", "cookie preferences", "cookie_preferences"),
]

def load_settings_snapshot():
    """
    Load settings_snapshot.json from privacyagentapp/settingslist/.

    tests/
      └── test_*.py
    settingslist/
      └── settings_snapshot.json
    """
    base = Path(__file__).resolve().parent
    snapshot_path = base.parent / "settingslist" / "settings_snapshot.json"

    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"settings_snapshot.json not found at {snapshot_path}"
        )

    return json.loads(snapshot_path.read_text(encoding="utf-8"))

def _simple_token_overlap(q: str, name: str) -> float:
    qt = set(q.lower().split())
    nt = set(name.lower().split())
    if not qt or not nt:
        return 0.0
    return len(qt & nt) / max(1, len(qt))

def _score(item, query: str) -> float:
    q = query.lower().strip()
    name = (item.get("name") or "").lower()
    desc = (item.get("description") or "").lower()

    s = 0.0
    if q == name:
        s += 50
    if q and q in name:
        s += 25
    if q and q in desc:
        s += 10

    s += 10 * _simple_token_overlap(q, name)
    s += 3 * _simple_token_overlap(q, desc)
    return s

def _find_candidates_from_snapshot(platform_items, query: str, limit: int = 3):
    scored = [( _score(it, query), it) for it in platform_items]
    scored = [(s, it) for (s, it) in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    # dedupe by setting_id
    out, seen = [], set()
    for _, it in scored:
        sid = it.get("setting_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(it)
        if len(out) >= limit:
            break
    return out

def test_snapshot_has_expected_platforms():
    snap = load_settings_snapshot()
    # These platforms exist in the provided snapshot
    for p in ["reddit", "instagram", "twitterX", "googleaccount", "facebook", "linkedin", "spotify", "zoom"]:
        assert p in snap, f"Missing platform {p} in snapshot"

def test_candidates_no_duplicates_and_top3_cap():
    snap = load_settings_snapshot()
    for plat, items in snap.items():
        cands = _find_candidates_from_snapshot(items, "account", limit=3)
        assert len(cands) <= 3
        ids = [c["setting_id"] for c in cands]
        assert len(ids) == len(set(ids)), f"Duplicate candidates for {plat}: {ids}"

def test_expected_candidates_present():
    snap = load_settings_snapshot()
    for plat, query, expected_id in SNAPSHOT_CANDIDATES:
        items = snap.get(plat, [])
        assert items, f"No items for platform {plat}"
        cands = _find_candidates_from_snapshot(items, query, limit=3)
        ids = [c["setting_id"] for c in cands]
        assert expected_id in ids, f"{plat}: query={query!r} expected {expected_id}, got {ids}"
