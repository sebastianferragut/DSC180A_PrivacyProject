import json
from pathlib import Path

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

def _simple_find_candidates(items, query: str, limit: int = 3):
    q = (query or "").lower().strip()
    scored = []
    for it in items:
        name = (it.get("name") or "").lower()
        desc = (it.get("description") or "").lower()
        s = 0
        if q == name:
            s += 50
        if q and q in name:
            s += 25
        if q and q in desc:
            s += 10
        # token overlap
        qt = set(q.split())
        nt = set(name.split())
        if qt and nt:
            s += 10 * (len(qt & nt) / max(1, len(qt)))
        if s > 0:
            scored.append((s, it))
    scored.sort(key=lambda x: x[0], reverse=True)

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

# These represent "Gemini interpretation outputs" (stubbed)
NLP_STUB_CASES = [
    # platform, normalized setting_query, target_value, expected setting_id
    ("reddit", "allow people to follow you", "off", "allow_people_to_follow_you"),
    ("instagram", "private account", "private", "private_account"),
    ("googleaccount", "web & app activity", "off", "web___app_activity"),
    ("facebook", "two-factor authentication", "on", "two_factor_authentication"),
    ("linkedin", "ads off linkedin", "off", "ads_off_linkedin"),
    ("spotify", "sign out everywhere", "on", "sign_out_everywhere"),  # value doesn't matter here; just routing
    ("zoom", "automatic recording", "on", "automatic_recording"),
]

def test_nlp_stubbed_routes_to_expected_candidate():
    snap = load_settings_snapshot()

    for platform, setting_query, target_value, expected_id in NLP_STUB_CASES:
        items = snap.get(platform, [])
        assert items, f"Missing platform {platform} in snapshot"
        cands = _simple_find_candidates(items, setting_query, limit=3)
        ids = [c["setting_id"] for c in cands]
        assert expected_id in ids, (
            f"{platform}: setting_query={setting_query!r} target={target_value!r} "
            f"expected {expected_id}, got {ids}"
        )
