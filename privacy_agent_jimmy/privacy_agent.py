#!/usr/bin/env python3
"""
Privacy Agent - Automated Zoom interaction using AI vision
"""

import subprocess
import time
import pyautogui
import psutil
from PIL import Image
import os
import sys
from datetime import datetime

class PrivacyAgent:
    def __init__(self):
        """Initialize the Privacy Agent"""
        self.zoom_app_name = "zoom.us"  # macOS Zoom app name
        self.screenshots_dir = "screenshots"
        pyautogui.FAILSAFE = True  # Enable failsafe (move mouse to corner to stop)
        
        # Create screenshots directory if it doesn't exist
        if not os.path.exists(self.screenshots_dir):
            os.makedirs(self.screenshots_dir)
        
    def is_zoom_running(self):
        """Check if Zoom is currently running"""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if self.zoom_app_name in proc.info['name'].lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False
    
    def open_zoom(self):
        """Open Zoom application"""
        print("Checking if Zoom is already running...")
        
        if self.is_zoom_running():
            print("Zoom is already running!")
            return True
            
        print("Opening Zoom application...")
        try:
            # On macOS, use 'open' command to launch Zoom
            result = subprocess.run(['open', '-a', 'zoom.us'], 
                                 capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print("Zoom application launched successfully!")
                
                # Wait for Zoom to fully load
                print("Waiting for Zoom to load...")
                time.sleep(5)
                
                # Additional delay to ensure app is fully loaded
                print("Giving app additional time to fully load...")
                time.sleep(5)
                
                # Verify Zoom is now running
                if self.is_zoom_running():
                    print("Zoom is now running and ready!")
                    return True
                else:
                    print("Warning: Zoom may not have started properly")
                    return False
            else:
                print(f"Failed to open Zoom: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("Timeout while trying to open Zoom")
            return False
        except Exception as e:
            print(f"Error opening Zoom: {e}")
            return False
    
    def take_screenshot(self, prefix="screenshot"):
        """Take a screenshot of the current screen"""
        try:
            # Generate timestamped filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{timestamp}.png"
            filepath = os.path.join(self.screenshots_dir, filename)
            
            screenshot = pyautogui.screenshot()
            screenshot.save(filepath)
            print(f"Screenshot saved as {filepath}")
            return filepath
        except Exception as e:
            print(f"Error taking screenshot: {e}")
            return None

def main():
    """Main function to test Zoom opening"""
    print("Privacy Agent - Starting Zoom Test")
    print("=" * 40)
    
    agent = PrivacyAgent()
    
    # Test opening Zoom
    success = agent.open_zoom()
    
    if success:
        print("\nZoom opened successfully!")
        
        # Take a screenshot to verify
        print("Taking screenshot...")
        screenshot_file = agent.take_screenshot("zoom_opened")
        
        if screenshot_file:
            print(f"Screenshot saved: {screenshot_file}")
        else:
            print("Failed to take screenshot")
    else:
        print("\nFailed to open Zoom")
        return 1
    
    print("\nTest completed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())

