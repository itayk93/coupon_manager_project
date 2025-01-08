# wsgi.py
from dotenv import load_dotenv
import os
from app import create_app
import logging

# טוען את משתני הסביבה מה-.env
load_dotenv()

# יוצר מופע Flask מהפונקציה create_app שבקובץ app/__init__.py
app = create_app()

if __name__ == "__main__":
    # הרצה מקומית (Development) – אפשר להדליק debug=True
    logging.basicConfig(level=logging.DEBUG)
    app.run(debug=True, host="0.0.0.0", port=5001)  # שינינו את הפורט ל-5001
