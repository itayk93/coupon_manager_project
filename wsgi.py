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
    import sys
    logging.basicConfig(level=logging.DEBUG)

    try:
        app.run(debug=os.getenv("FLASK_DEBUG", "true").lower() == "true", host="0.0.0.0", port=5001)
    except SystemExit as e:
        logging.error(f"אפליקציית Flask נסגרה עם קוד יציאה: {e.code}")
        sys.exit(e.code)