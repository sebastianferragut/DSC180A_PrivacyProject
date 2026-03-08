"""
Setup script for Privacy Screenshot Classifier

This script helps set up the environment and dependencies
for the privacy screenshot classification system.
"""

import os
import sys
import subprocess
import json
from pathlib import Path


def check_python_version():
    """Check if Python version is compatible."""
    print("🐍 Checking Python version...")
    
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        print(f"Current version: {sys.version}")
        return False
    
    print(f"✅ Python {sys.version.split()[0]} is compatible")
    return True


def check_api_key():
    """Check if Gemini API key is set."""
    print("\n🔑 Checking API key...")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  GEMINI_API_KEY environment variable not set")
        print("Please set your API key:")
        print("export GEMINI_API_KEY='your_api_key_here'")
        return False
    
    print("✅ GEMINI_API_KEY is set")
    return True


def create_directories():
    """Create necessary directories."""
    print("\n📁 Creating directories...")
    
    directories = [
        "privacy_screenshots",
        "results",
        "logs"
    ]
    
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        print(f"✅ Created directory: {directory}")


def create_sample_files():
    """Create sample configuration files."""
    print("\n📄 Creating sample files...")
    
    # Create .env template
    env_template = """# Privacy Screenshot Classifier Environment Variables
# Copy this file to .env and fill in your values

# Google Gemini API Key (required)
GEMINI_API_KEY=your_api_key_here

# Optional: Custom model settings
# GEMINI_MODEL_ID=gemini-2.5-pro
# GEMINI_TEMPERATURE=0.1
# GEMINI_MAX_TOKENS=2048
"""
    
    with open(".env.template", "w") as f:
        f.write(env_template)
    print("✅ Created .env.template")
    
    # Create sample configuration
    sample_config = {
        "api_key": "your_api_key_here",
        "model_id": "gemini-2.5-pro",
        "temperature": 0.1,
        "max_tokens": 2048,
        "output_directory": "results",
        "log_level": "INFO"
    }
    
    with open("config_sample.json", "w") as f:
        json.dump(sample_config, f, indent=2)
    print("✅ Created config_sample.json")


def check_dependencies():
    """Check if required dependencies are installed."""
    print("\n📦 Checking dependencies...")
    
    required_packages = [
        "google-genai",
        "pillow",
        "requests",
        "pyyaml"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
            print(f"✅ {package} is installed")
        except ImportError:
            print(f"❌ {package} is missing")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️  Missing packages: {', '.join(missing_packages)}")
        print("Install them with: pip install -r requirements.txt")
        return False
    
    print("✅ All required packages are installed")
    return True


def install_dependencies():
    """Install required dependencies."""
    print("\n📦 Installing dependencies...")
    
    try:
        # Try to install from requirements.txt
        if os.path.exists("requirements.txt"):
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                         check=True)
            print("✅ Dependencies installed from requirements.txt")
        else:
            # Install core packages
            core_packages = [
                "google-genai",
                "pillow",
                "requests",
                "pyyaml"
            ]
            
            for package in core_packages:
                subprocess.run([sys.executable, "-m", "pip", "install", package], 
                             check=True)
                print(f"✅ Installed {package}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False


def run_tests():
    """Run basic tests."""
    print("\n🧪 Running tests...")
    
    try:
        # Import and test the classifier
        from screenshot_classification import PrivacyScreenshotClassifier
        
        # Test initialization (without API key)
        try:
            classifier = PrivacyScreenshotClassifier("dummy_key")
            print("✅ Classifier can be imported and initialized")
        except Exception as e:
            if "API key" in str(e):
                print("✅ Classifier structure is correct (API key validation working)")
            else:
                print(f"❌ Classifier test failed: {e}")
                return False
        
        return True
        
    except ImportError as e:
        print(f"❌ Import test failed: {e}")
        return False


def create_quick_start_guide():
    """Create a quick start guide."""
    print("\n📚 Creating quick start guide...")
    
    guide = """# Quick Start Guide

## 1. Set up your API key
```bash
export GEMINI_API_KEY="your_api_key_here"
```

## 2. Test the classifier
```bash
python test_classifier.py
```

## 3. Run example usage
```bash
python example_usage.py
```

## 4. Analyze your screenshots
```python
from screenshot_classification import PrivacyScreenshotClassifier

classifier = PrivacyScreenshotClassifier()
result = classifier.analyze_screenshot("your_screenshot.png")
print(result)
```

## 5. Batch process multiple screenshots
```python
results = classifier.batch_classify("screenshots_directory/", "results.json")
```

## Troubleshooting
- Make sure your API key is set correctly
- Check that your screenshots are in supported formats (PNG, JPG, etc.)
- Ensure you have sufficient API quota
"""
    
    with open("QUICK_START.md", "w") as f:
        f.write(guide)
    print("✅ Created QUICK_START.md")


def main():
    """Run the setup process."""
    print("🚀 Privacy Screenshot Classifier Setup")
    print("=" * 50)
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Create directories
    create_directories()
    
    # Create sample files
    create_sample_files()
    
    # Check dependencies
    if not check_dependencies():
        print("\n🔧 Installing missing dependencies...")
        if not install_dependencies():
            print("❌ Failed to install dependencies")
            return False
    
    # Run tests
    if not run_tests():
        print("❌ Tests failed")
        return False
    
    # Check API key
    api_key_set = check_api_key()
    
    # Create quick start guide
    create_quick_start_guide()
    
    # Summary
    print("\n🎉 Setup Complete!")
    print("=" * 30)
    
    if api_key_set:
        print("✅ Ready to use! You can now:")
        print("  1. Run: python test_classifier.py")
        print("  2. Run: python example_usage.py")
        print("  3. Add screenshots to privacy_screenshots/ directory")
        print("  4. Run: python screenshot-classification.py")
    else:
        print("⚠️  Almost ready! Please:")
        print("  1. Set your GEMINI_API_KEY environment variable")
        print("  2. Run: python test_classifier.py")
        print("  3. Run: python example_usage.py")
    
    print("\n📚 Documentation:")
    print("  - README.md: Full documentation")
    print("  - QUICK_START.md: Quick start guide")
    print("  - example_usage.py: Usage examples")
    print("  - test_classifier.py: Test suite")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
