#!/usr/bin/env python3
"""
Initialize admin settings for automatic logo fetching
This script should be run once to set up the initial admin setting
"""

import os
import sys

# Add the project directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.extensions import db  
from app.models import AdminSettings

def init_logo_settings():
    """Initialize the auto logo fetch setting"""
    app = create_app()
    
    with app.app_context():
        # Check if setting already exists
        existing_setting = AdminSettings.query.filter_by(setting_key="auto_fetch_company_logos").first()
        
        if not existing_setting:
            # Create the setting with default value True (enabled)
            AdminSettings.set_setting(
                "auto_fetch_company_logos",
                True,
                setting_type="boolean", 
                description="Enable automatic logo fetching when creating new companies"
            )
            db.session.commit()
            print("✅ Created auto_fetch_company_logos setting (enabled by default)")
        else:
            print(f"⚠️  Setting already exists: {existing_setting.setting_value}")
        
        # Show current status
        current_value = AdminSettings.get_setting("auto_fetch_company_logos")
        status = "מופעל" if current_value else "מבוטל"
        print(f"🔧 Current status: {status}")

if __name__ == "__main__":
    init_logo_settings()