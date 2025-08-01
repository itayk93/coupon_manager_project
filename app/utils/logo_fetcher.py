# app/utils/logo_fetcher.py

import os
import requests
import hashlib
from PIL import Image
from io import BytesIO
from urllib.parse import urljoin, urlparse
import logging
from flask import current_app

logger = logging.getLogger(__name__)

class LogoFetcher:
    """
    Class for fetching and processing company logos from various sources
    """
    
    # API endpoints for logo fetching
    CLEARBIT_API = "https://logo.clearbit.com/{domain}"
    GOOGLE_FAVICON_API = "https://www.google.com/s2/favicons?domain={domain}&sz=128"
    
    # Image processing settings
    LOGO_SIZE = (128, 128)
    MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
    ALLOWED_FORMATS = ['PNG', 'JPEG', 'JPG', 'WebP']
    TIMEOUT = 10  # seconds
    
    def __init__(self):
        self.static_images_path = os.path.join(current_app.root_path, 'static', 'images')
        self.ensure_images_directory()
    
    def ensure_images_directory(self):
        """Ensure the images directory exists"""
        if not os.path.exists(self.static_images_path):
            os.makedirs(self.static_images_path, exist_ok=True)
    
    def is_auto_fetch_enabled(self):
        """Check if automatic logo fetching is enabled in admin settings"""
        from app.models import AdminSettings
        return AdminSettings.get_setting('auto_fetch_company_logos', default=True)
    
    def clean_company_name_for_domain(self, company_name):
        """
        Convert company name to a potential domain name
        מחסני חשמל -> machsaney-chashmal
        מקדונלדס -> mcdonalds
        """
        # Basic cleaning - remove Hebrew characters, special chars
        import re
        
        # Common Hebrew to English mappings for major companies
        hebrew_to_english = {
            'מקדונלדס': 'mcdonalds',
            'בורגר קינג': 'burgerking', 
            'KFC': 'kfc',
            'פיצה האט': 'pizzahut',
            'דומינוס': 'dominos',
            'סופרפארם': 'super-pharm',
            'רמי לוי': 'rami-levy',
            'שופרסל': 'shufersal',
            'מגה': 'mega',
            'טיב טעם': 'tivtaam',
            'יוחננוף': 'yochananof',
            'רולדין': 'roladin',
            'ארקפה': 'arcaffe',
            'קפה קפה': 'cafe-cafe',
            'גולדה': 'golda',
            'גרג': 'greg',
        }
        
        company_lower = company_name.lower().strip()
        
        # Check if we have a direct mapping
        if company_lower in hebrew_to_english:
            return hebrew_to_english[company_lower]
        
        # Generic cleaning for other names
        # Remove Hebrew characters and keep only English letters, numbers, and hyphens
        cleaned = re.sub(r'[^\w\s-]', '', company_name)
        cleaned = re.sub(r'\s+', '-', cleaned.strip())
        cleaned = cleaned.lower()
        
        return cleaned if cleaned else company_name.lower()
    
    def fetch_logo_from_clearbit(self, company_name):
        """Fetch logo from Clearbit API"""
        try:
            domain = self.clean_company_name_for_domain(company_name)
            
            # Try different domain variations
            domain_variations = [
                f"{domain}.com",
                f"{domain}.co.il", 
                f"{domain}.co.uk",
                f"{domain}.org",
                domain
            ]
            
            for domain_var in domain_variations:
                url = self.CLEARBIT_API.format(domain=domain_var)
                logger.info(f"Trying Clearbit API for {company_name} with domain: {domain_var}")
                
                response = requests.get(url, timeout=self.TIMEOUT)
                if response.status_code == 200 and len(response.content) > 1000:  # Ensure it's not just an error image
                    logger.info(f"Successfully fetched logo from Clearbit for {company_name}")
                    return response.content
                    
        except Exception as e:
            logger.warning(f"Clearbit API failed for {company_name}: {str(e)}")
        
        return None
    
    def fetch_logo_from_google_favicon(self, company_name):
        """Fetch logo from Google Favicon API"""
        try:
            domain = self.clean_company_name_for_domain(company_name)
            
            # Try different domain variations
            domain_variations = [
                f"{domain}.com",
                f"{domain}.co.il",
                f"www.{domain}.com"
            ]
            
            for domain_var in domain_variations:
                url = self.GOOGLE_FAVICON_API.format(domain=domain_var)
                logger.info(f"Trying Google Favicon API for {company_name} with domain: {domain_var}")
                
                response = requests.get(url, timeout=self.TIMEOUT)
                if response.status_code == 200 and len(response.content) > 500:
                    logger.info(f"Successfully fetched favicon from Google for {company_name}")
                    return response.content
                    
        except Exception as e:
            logger.warning(f"Google Favicon API failed for {company_name}: {str(e)}")
        
        return None
    
    def process_and_save_image(self, image_data, company_name, company_id):
        """Process the downloaded image and save it"""
        try:
            # Check file size
            if len(image_data) > self.MAX_FILE_SIZE:
                logger.warning(f"Image too large for {company_name}: {len(image_data)} bytes")
                return None
            
            # Open and process image
            image = Image.open(BytesIO(image_data))
            
            # Convert to RGB if necessary (for PNG with transparency)
            if image.mode in ('RGBA', 'LA', 'P'):
                # Create white background
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Resize image
            image = image.resize(self.LOGO_SIZE, Image.Resampling.LANCZOS)
            
            # Generate filename
            # Use company name and ID to create unique filename
            safe_name = "".join(c for c in company_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_name = safe_name.replace(' ', '_').lower()[:50]  # Limit length
            filename = f"{safe_name}_{company_id}.png"
            
            # Full path for saving
            file_path = os.path.join(self.static_images_path, filename)
            
            # Save image
            image.save(file_path, 'PNG', optimize=True)
            
            # Return relative path for database storage
            relative_path = f"images/{filename}"
            logger.info(f"Successfully saved logo for {company_name} as {relative_path}")
            
            return relative_path
            
        except Exception as e:
            logger.error(f"Failed to process image for {company_name}: {str(e)}")
            return None
    
    def fetch_company_logo(self, company_name, company_id):
        """
        Main method to fetch and process company logo
        Returns the relative path to the saved logo or None if failed
        """
        
        # Check if auto-fetch is enabled
        if not self.is_auto_fetch_enabled():
            logger.info(f"Auto logo fetch is disabled, skipping {company_name}")
            return None
        
        logger.info(f"Starting logo fetch for company: {company_name} (ID: {company_id})")
        
        # Try Clearbit first (higher quality)
        image_data = self.fetch_logo_from_clearbit(company_name)
        
        # Fallback to Google Favicon
        if not image_data:
            image_data = self.fetch_logo_from_google_favicon(company_name)
        
        # Process and save the image
        if image_data:
            return self.process_and_save_image(image_data, company_name, company_id)
        
        logger.warning(f"No logo found for company: {company_name}")
        return None
    
    def update_company_logo_path(self, company_id, logo_path):
        """Update the company's logo path in database"""
        try:
            from app.extensions import db
            from app.models import Company
            
            company = Company.query.get(company_id)
            if company:
                company.image_path = logo_path
                db.session.commit()
                logger.info(f"Updated logo path for company {company.name}: {logo_path}")
                return True
            else:
                logger.error(f"Company with ID {company_id} not found")
                return False
        except Exception as e:
            logger.error(f"Failed to update company logo path: {str(e)}")
            from app.extensions import db
            db.session.rollback()
            return False
    
    def fetch_and_update_company_logo(self, company_name, company_id):
        """
        Complete workflow: fetch logo and update database
        Returns True if successful, False otherwise
        """
        try:
            logo_path = self.fetch_company_logo(company_name, company_id)
            
            if logo_path:
                success = self.update_company_logo_path(company_id, logo_path)
                if success:
                    logger.info(f"Successfully fetched and updated logo for {company_name}")
                    return True
            
            # If we reach here, logo fetch failed - set default logo
            self.update_company_logo_path(company_id, "images/default_logo.png")
            logger.info(f"Set default logo for {company_name}")
            return False
            
        except Exception as e:
            logger.error(f"Complete logo fetch workflow failed for {company_name}: {str(e)}")
            # Ensure company has some logo path
            self.update_company_logo_path(company_id, "images/default_logo.png")
            return False


# Convenience function for easy import
def fetch_company_logo(company_name, company_id):
    """
    Convenience function to fetch logo for a company
    """
    fetcher = LogoFetcher()
    return fetcher.fetch_and_update_company_logo(company_name, company_id)