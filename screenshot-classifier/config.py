"""
Configuration file for Privacy Screenshot Classifier

This file contains configuration settings that can be customized
for different use cases and requirements.
"""

# API Configuration
GEMINI_MODEL_ID = 'gemini-2.5-pro'
GEMINI_TEMPERATURE = 0.1
GEMINI_MAX_TOKENS = 2048

# Image Processing Configuration
SUPPORTED_IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
MAX_IMAGE_SIZE_MB = 10  # Maximum image size in MB

# Output Configuration
DEFAULT_OUTPUT_DIR = "results"
DEFAULT_OUTPUT_FILE = "classification_results.json"
INCLUDE_TIMESTAMPS = True
INCLUDE_CONFIDENCE_SCORES = True

# Privacy Categories Configuration
PRIVACY_CATEGORIES = {
    "data_collection": {
        "keywords": [
            "data collection", "collect data", "analytics", "tracking", 
            "telemetry", "usage data", "performance data", "crash reports"
        ],
        "description": "Settings related to data collection and analytics",
        "priority": "high"
    },
    "camera_microphone": {
        "keywords": [
            "camera", "microphone", "video", "audio", "recording", 
            "permissions", "access", "capture", "stream"
        ],
        "description": "Camera and microphone access settings",
        "priority": "high"
    },
    "location_privacy": {
        "keywords": [
            "location", "gps", "geolocation", "where you are", 
            "position", "coordinates", "address", "nearby"
        ],
        "description": "Location and geolocation privacy settings",
        "priority": "high"
    },
    "personal_information": {
        "keywords": [
            "personal info", "profile", "name", "email", "phone", 
            "address", "contact", "identity", "demographics"
        ],
        "description": "Personal information and profile settings",
        "priority": "medium"
    },
    "communication_privacy": {
        "keywords": [
            "messages", "chat", "communication", "calls", "meeting", 
            "conversation", "dialogue", "discussion", "correspondence"
        ],
        "description": "Communication and messaging privacy settings",
        "priority": "medium"
    },
    "account_security": {
        "keywords": [
            "security", "password", "authentication", "login", 
            "account", "access", "verification", "two-factor"
        ],
        "description": "Account security and authentication settings",
        "priority": "high"
    },
    "sharing_settings": {
        "keywords": [
            "share", "public", "private", "visibility", "who can see", 
            "audience", "followers", "friends", "connections"
        ],
        "description": "Content sharing and visibility settings",
        "priority": "medium"
    },
    "notification_privacy": {
        "keywords": [
            "notifications", "alerts", "reminders", "email notifications",
            "push notifications", "updates", "announcements"
        ],
        "description": "Notification and alert privacy settings",
        "priority": "low"
    },
    "data_retention": {
        "keywords": [
            "retention", "delete", "remove", "expire", "storage", 
            "history", "archive", "backup", "cleanup"
        ],
        "description": "Data retention and deletion settings",
        "priority": "high"
    },
    "third_party_sharing": {
        "keywords": [
            "third party", "partners", "integrations", "external", 
            "api", "affiliates", "vendors", "service providers"
        ],
        "description": "Third-party data sharing and integration settings",
        "priority": "high"
    }
}

# Analysis Configuration
ANALYSIS_PROMPT_TEMPLATE = """
You are a privacy settings expert analyzing a screenshot of a privacy settings page.

Analyze the screenshot and provide detailed information about:

1. **Application/Service**: What application or service is this privacy settings page for?
2. **Page Type**: What type of privacy settings page is this?
3. **Privacy Categories Present**: Which privacy categories are visible?
4. **Specific Settings**: List any specific privacy settings, toggles, or options visible.
5. **User Actions Available**: What privacy-related actions can a user take?
6. **Privacy Level**: Rate the overall privacy-friendliness (1-10, where 10 is most privacy-friendly).
7. **Key Concerns**: Identify any potential privacy concerns or red flags.
8. **Recommendations**: Provide brief recommendations for privacy-conscious users.

Please respond in JSON format with the following structure:
{{
    "application": "string",
    "page_type": "string", 
    "privacy_categories": ["list", "of", "categories"],
    "specific_settings": ["list", "of", "visible", "settings"],
    "user_actions": ["list", "of", "available", "actions"],
    "privacy_level": number,
    "key_concerns": ["list", "of", "concerns"],
    "recommendations": ["list", "of", "recommendations"],
    "confidence": number
}}

Be thorough and accurate in your analysis. Focus on privacy-related content and settings.
"""

# Batch Processing Configuration
BATCH_PROCESSING = {
    "max_concurrent": 5,  # Maximum concurrent API calls
    "delay_between_calls": 1.0,  # Delay in seconds between API calls
    "retry_attempts": 3,  # Number of retry attempts for failed calls
    "retry_delay": 2.0,  # Delay between retry attempts
}

# Logging Configuration
LOGGING = {
    "level": "INFO",  # DEBUG, INFO, WARNING, ERROR
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": "classifier.log",
    "max_size_mb": 10,
    "backup_count": 5
}

# Privacy Level Thresholds
PRIVACY_LEVELS = {
    "excellent": 9,  # 9-10
    "good": 7,       # 7-8
    "fair": 5,       # 5-6
    "poor": 3,       # 3-4
    "very_poor": 1   # 1-2
}

# Output Templates
OUTPUT_TEMPLATES = {
    "summary": """
Privacy Analysis Summary
=======================
Application: {application}
Page Type: {page_type}
Privacy Level: {privacy_level}/10 ({level_description})
Confidence: {confidence}

Categories Detected: {categories_count}
- {categories_list}

Key Concerns: {concerns_count}
- {concerns_list}

Recommendations: {recommendations_count}
- {recommendations_list}
""",
    
    "detailed": """
Detailed Privacy Analysis
========================
Image: {image_path}
Timestamp: {timestamp}
Model: {model_used}

Application: {application}
Page Type: {page_type}

Privacy Categories:
{privacy_categories}

Specific Settings:
{specific_settings}

User Actions:
{user_actions}

Privacy Level: {privacy_level}/10
Key Concerns: {key_concerns}
Recommendations: {recommendations}

Confidence: {confidence}
"""
}
