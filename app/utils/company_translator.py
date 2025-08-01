# app/utils/company_translator.py

import os
import openai
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CompanyTranslator:
    """
    Class for translating Hebrew company names to English using OpenAI GPT-4o-mini
    """
    
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning("OpenAI API key not found in environment variables")
            return
            
        openai.api_key = self.api_key
    
    def translate_company_name(self, hebrew_name: str) -> Optional[str]:
        """
        Translate Hebrew company name to English using GPT-4o-mini
        Returns the English name or None if translation fails
        """
        if not self.api_key:
            logger.warning("Cannot translate - OpenAI API key not available")
            return None
            
        try:
            prompt = f"""
            Translate the following Hebrew company name to English. 
            Return ONLY the English company name, nothing more.
            If it's already in English, return it as is.
            If it's a well-known international brand, use the official English name.
            
            Hebrew company name: {hebrew_name}
            
            Examples:
            מקדונלדס -> McDonald's
            בורגר קינג -> Burger King  
            מחסני חשמל -> Mahsanei Hashmal
            שופרסל -> Shufersal
            רמי לוי -> Rami Levy
            """
            
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                max_tokens=50,
                temperature=0.1,
                timeout=10
            )
            
            english_name = response.choices[0].message.content.strip()
            
            # Clean up the response - remove quotes and extra text
            english_name = english_name.replace('"', '').replace("'", "")
            
            # If response contains explanation, take only the first part
            if '->' in english_name:
                english_name = english_name.split('->')[1].strip()
            
            # Remove any remaining explanatory text
            lines = english_name.split('\n')
            english_name = lines[0].strip()
            
            logger.info(f"Translated '{hebrew_name}' -> '{english_name}'")
            return english_name
            
        except openai.error.RateLimitError:
            logger.warning(f"OpenAI rate limit exceeded for translation of '{hebrew_name}'")
            return None
        except openai.error.OpenAIError as e:
            logger.error(f"OpenAI API error translating '{hebrew_name}': {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error translating '{hebrew_name}': {str(e)}")
            return None
    
    def get_company_domain_suggestions(self, company_name: str) -> list:
        """
        Get domain suggestions for a company name (both Hebrew and English)
        """
        domains = []
        
        # Try to translate to English first
        english_name = self.translate_company_name(company_name)
        
        if english_name and english_name.lower() != company_name.lower():
            # Use English name for domain suggestions
            base_name = english_name.lower()
            base_name = base_name.replace(' ', '-').replace('&', 'and').replace("'", "")
            base_name = ''.join(c for c in base_name if c.isalnum() or c == '-')
            
            domains.extend([
                f"{base_name}.com",
                f"{base_name}.co.il", 
                f"{base_name}.net",
                f"www.{base_name}.com"
            ])
            
            # Also try without hyphens
            simple_name = base_name.replace('-', '')
            if simple_name != base_name:
                domains.extend([
                    f"{simple_name}.com",
                    f"{simple_name}.co.il"
                ])
        
        # Fallback to original name processing
        original_name = company_name.lower()
        original_name = original_name.replace(' ', '-').replace('&', 'and')
        original_name = ''.join(c for c in original_name if c.isalnum() or c == '-')
        
        domains.extend([
            f"{original_name}.com",
            f"{original_name}.co.il"
        ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_domains = []
        for domain in domains:
            if domain not in seen:
                seen.add(domain)
                unique_domains.append(domain)
        
        return unique_domains[:8]  # Limit to 8 domain attempts


# Convenience function
def translate_company_name(hebrew_name: str) -> Optional[str]:
    """
    Convenience function to translate a company name
    """
    translator = CompanyTranslator()
    return translator.translate_company_name(hebrew_name)