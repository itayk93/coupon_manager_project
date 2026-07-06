import os
import sys
from dotenv import load_dotenv

load_dotenv()
os.environ['FLASK_ENV'] = 'development'
os.environ['SELENIUM_HEADLESS'] = 'false'
os.environ['DEBUG_MODE'] = 'True'

from app import create_app
from app.models import Coupon
from app.helpers import get_coupon_data_with_retry
import logging

logging.basicConfig(level=logging.INFO)

app = create_app()
with app.app_context():
    c = Coupon.query.filter(Coupon.company.ilike('%GoodPharm%'), Coupon.status == 'פעיל', Coupon.auto_download_details.isnot(None)).first()
    if c:
        print(f"Running scrape for coupon: {c.code}, {c.company}")
        try:
            df = get_coupon_data_with_retry(c)
            print("Scraping completed.")
            if df is not None:
                print(df.head())
            else:
                print("DataFrame is None")
        except Exception as e:
            print("Error during scraping:", e)
    else:
        print("Coupon not found.")
