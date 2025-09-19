# app/template_helpers.py
from flask import current_app
from app.extensions import cache
from app.models import Coupon, Company, Tag


@cache.memoize(timeout=600)  # 10 minutes
def get_template_companies():
    """Get companies for template dropdown - cached"""
    return Company.query.order_by(Company.name).all()


@cache.memoize(timeout=300)  # 5 minutes  
def get_template_tags():
    """Get tags for template - cached"""
    return Tag.query.order_by(Tag.name).all()


@cache.memoize(timeout=900)  # 15 minutes
def get_company_logo_mapping():
    """Get company logo mapping - cached"""
    companies = get_template_companies()
    company_logo_mapping = {c.name.lower(): c.image_path for c in companies}
    
    # Set default logo for companies without images
    for company_name in company_logo_mapping:
        if not company_logo_mapping[company_name]:
            company_logo_mapping[company_name] = "images/default.png"
    
    return company_logo_mapping


def register_template_helpers(app):
    """Register template helper functions"""
    @app.context_processor
    def inject_cached_data():
        return {
            'get_template_companies': get_template_companies,
            'get_template_tags': get_template_tags,
            'get_company_logo_mapping': get_company_logo_mapping,
        }