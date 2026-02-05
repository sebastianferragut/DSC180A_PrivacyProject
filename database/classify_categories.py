import json
import numpy as np
from pathlib import Path

from google import genai
client = genai.Client()

EMBED_MODEL = "models/text-embedding-004"

INPUT_PATH = Path("data/extracted_settings_with_urls_and_layers.json")
OUTPUT_PATH = Path("data/extracted_settings_with_urls_and_layers_classified.json")
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

def classify_setting(setting, category_embeddings):
    """
    Classify a single privacy setting into one of the big categories.
    """
    text = " ".join([
        setting.get("setting", ""),
        setting.get("description", ""),
        setting.get("state", "")
    ]).strip()

    if not text:
        return "uncategorized"

    resp = client.models.embed_content(
        model=EMBED_MODEL,
        contents=[text]
    )
    emb = resp.embeddings[0].values

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
    print("[INFO] Loading extracted settings with URLs and layers...")
    data = json.loads(INPUT_PATH.read_text())

    print("[INFO] Loading or computing category embeddings...")
    category_embeddings = load_or_compute_category_embeddings()

    print("[INFO] Classifying individual settings...")
    total = 0

    for block in data:
        for setting in block.get("all_settings", []):
            setting["category"] = classify_setting(setting, category_embeddings)
            total += 1
            if total % 10 == 0:
                print(f"[INFO] Classified {total} settings...")


    OUTPUT_PATH.write_text(json.dumps(data, indent=2))
    print(f"[DONE] Classified {total} settings → {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
