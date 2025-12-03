# BIG_CATEGORIES = {
#     "identity_personal_info": [
#         "personal", "name", "email", "phone", "contact",
#         "profile", "birthday", "age", "gender", "demographic"
#     ],

#     "security_authentication": [
#         "security", "password", "authentication", "login",
#         "two-factor", "2fa", "verification", "identity confirmation",
#         "encryption"
#     ],

#     "device_sensor_access": [
#         "camera", "microphone", "audio", "video",
#         "record", "recording", "device", "sensor",
#         "screen sharing", "screen record"
#     ],

#     "data_collection_tracking": [
#         "collect", "collection", "tracking", "analytics", "telemetry",
#         "ad", "ads", "diagnostic", "inferred", "activity",
#         "search history"
#     ],

#     "data_sharing_third_parties": [
#         "third party", "partners", "affiliates", "sharing",
#         "integration", "connected", "external", "api",
#         "cookies"
#     ],

#     "visibility_audience": [
#         "visibility", "public", "private", "audience",
#         "who can see", "followers", "profile viewing",
#         "discoverability"
#     ],

#     "communication_notifications": [
#         "messages", "chat", "messaging", "calls",
#         "notifications", "alerts", "read receipts",
#         "typing indicators"
#     ]
# }

    
import json
import numpy as np
from pathlib import Path

from google import genai
client = genai.Client()

EMBED_MODEL = "models/text-embedding-004"

INPUT_PATH = Path("data/all_platforms_images.json")
OUTPUT_PATH = Path("data/all_platforms_classified.json")
CATEGORY_EMBED_PATH = Path("data/category_embeddings.json")

# -------------------------------------------
# CATEGORY DEFINITIONS
# -------------------------------------------

CATEGORIES = {
    "security_authentication": """
        Settings related to passwords, login security, account protection,
        two-factor authentication, passkeys, active sessions, identity
        verification, suspicious activity, and saved devices.
    """,

    "identity_personal_info": """
        Settings related to personal profile details such as name, birthday,
        gender, demographic data, identity verification information, and
        contact information like phone numbers and email addresses.
    """,

    "device_sensor_access": """
        Settings related to device access such as camera, microphone, audio,
        video, sensors, screen sharing, and recording permissions.
    """,

    "data_collection_tracking": """
        Settings related to analytics, tracking, telemetry, search history,
        ad preferences, inference data, AI training data, off-platform
        activity, and any collected data used for personalization.
    """,

    "data_sharing_third_parties": """
        Settings related to third-party sharing, partner integrations,
        affiliates, external apps, connected apps, cookies, API access,
        and cross-service data flows.
    """,

    "visibility_audience": """
        Settings controlling who can view your profile, posts, connections,
        last name visibility, page visibility, discoverability, followers,
        blocking, and visibility of your actions on the platform.
    """,

    "communication_notifications": """
        Settings for messaging, calls, chat, comments, notifications,
        alerts, read receipts, typing indicators, and communication preferences.
    """
}

# -------------------------------------------
# Cosine similarity
# -------------------------------------------

def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# -------------------------------------------
# Category embedding handling
# -------------------------------------------

def compute_category_embeddings():
    print("[INFO] Computing category embeddings with Gemini...")

    cat_emb = {}
    for cat_name, text in CATEGORIES.items():
        resp = client.models.embed_content(
            model=EMBED_MODEL,
            contents=[text.strip()],
        )
        cat_emb[cat_name] = resp.embeddings[0].values

    CATEGORY_EMBED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATEGORY_EMBED_PATH.write_text(json.dumps(cat_emb, indent=2))
    print(f"[DONE] Saved category embeddings → {CATEGORY_EMBED_PATH}")

    return cat_emb


def load_or_compute_category_embeddings():
    if CATEGORY_EMBED_PATH.exists():
        print("[INFO] Loading cached category embeddings...")
        return json.loads(CATEGORY_EMBED_PATH.read_text())

    return compute_category_embeddings()


# -------------------------------------------
# Screenshot classification
# -------------------------------------------

def classify_entry(entry, category_embeddings):
    # Combine all text from settings in this screenshot
    full_text = " ".join(
        f"{s.get('setting','')}. {s.get('description','')}. {s.get('state','')}."
        for s in entry.get("settings", [])
    ).strip()

    if not full_text:
        return "uncategorized"

    # Get embedding for screenshot content
    resp = client.models.embed_content(
        model=EMBED_MODEL,
        contents=[full_text]
    )
    emb = resp.embeddings[0].values

    # Compare to each category
    best_cat = None
    best_score = -1

    for cat_name, cat_emb in category_embeddings.items():
        score = cosine_similarity(emb, cat_emb)
        if score > best_score:
            best_score = score
            best_cat = cat_name

    return best_cat


# -------------------------------------------
# MAIN
# -------------------------------------------

def main():
    print("[INFO] Loading screenshot dataset...")
    entries = json.loads(INPUT_PATH.read_text())

    print("[INFO] Loading or computing category embeddings...")
    category_embeddings = load_or_compute_category_embeddings()

    print("[INFO] Classifying screenshots using Gemini embeddings...")
    for entry in entries:
        entry["category"] = classify_entry(entry, category_embeddings)

    OUTPUT_PATH.write_text(json.dumps(entries, indent=2))
    print(f"[DONE] Classification written to → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
