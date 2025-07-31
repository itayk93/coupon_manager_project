# Claude AI Assistant Instructions for Coupon Manager Project

## Project Overview
This is a Flask-based coupon management system with marketplace functionality, user authentication, admin panel, Telegram integration, and comprehensive analytics. Always refer to `PROJECT_DOCUMENTATION.md` for complete routes and endpoints documentation.

## Key Project Information

### Main Application Files
- `app.py` - Main Flask application entry point
- `app/__init__.py` - Application factory with blueprint registration
- `wsgi.py` - WSGI configuration for deployment
- `app/models.py` - Database models (User, Coupon, Transaction, etc.)
- `app/config.py` - Configuration settings
- `app/extensions.py` - Flask extensions initialization

### Routes Structure
The application uses Flask Blueprints organized in `app/routes/`:
- `auth_routes.py` - Authentication (login, register, OAuth)
- `profile_routes.py` - User profiles and dashboard
- `coupons_routes.py` - Coupon CRUD operations
- `marketplace_routes.py` - Coupon marketplace and trading
- `transactions_routes.py` - Buy/sell transaction management
- `admin_routes/` - Admin panel functionality
- `telegram_routes.py` - Telegram bot integration
- `sharing_routes.py` - Coupon sharing system
- `statistics_routes.py` - Analytics and reporting

### Database
- Uses SQLAlchemy ORM
- Main models: User, Coupon, Transaction, Company, Tag, Newsletter
- Migration files in `migrations/versions/`

### Frontend
- Jinja2 templates in `app/templates/`
- Bootstrap-based UI with custom CSS in `app/static/`
- AJAX functionality for dynamic interactions

## Development Guidelines

### When Adding New Features
1. **Always update PROJECT_DOCUMENTATION.md** when adding new routes or endpoints
2. Create appropriate route in the relevant blueprint file
3. Add corresponding template if needed
4. Update models if database changes are required
5. Create migration file for schema changes
6. **If adding new library imports, update requirements.txt with the new dependencies**
7. **Update project_structure.txt with new files/directories added**
8. Test both functionality and security
9. **Automatically commit all changes at the end of each session**

### When Modifying Existing Code
1. Check `PROJECT_DOCUMENTATION.md` for current route information
2. Maintain existing URL patterns and HTTP methods
3. Preserve authentication decorators and permissions
4. **If adding new library imports, update requirements.txt with the new dependencies**
5. **Update project_structure.txt if file structure changes**
6. Update documentation after changes
7. Consider backward compatibility
8. **Automatically commit all changes at the end of each session**

### Security Considerations
- All admin routes require `@admin_required` decorator
- User authentication uses `@login_required` from Flask-Login
- CSRF protection enabled via Flask-WTF
- Sensitive operations use secure tokens
- File uploads are validated and restricted

### Code Patterns
- Use Flask Blueprints for route organization
- Follow existing naming conventions (snake_case for functions/variables)
- Use SQLAlchemy ORM for database operations
- Implement proper error handling and logging
- Use flash messages for user feedback
- **When importing new libraries, always update requirements.txt with proper version specifications**

### Testing & Deployment
- Test all routes after modifications
- Check both authenticated and unauthenticated access
- Verify admin functionality separately
- Run migrations before deployment
- Check static file serving

### Port Management
**CRITICAL**: When running the Flask application for testing, always kill the port processes at the end of the session to prevent port conflicts.

#### Port Cleanup Process:
1. **After running the Flask app** (typically on port 10000 or 5000)
2. **Before ending the session**, run: `lsof -ti:10000 | xargs kill -9` (replace 10000 with the actual port used)
3. **Alternative command for multiple ports**: `pkill -f "flask run"` or `pkill -f "python app.py"`
4. **Verify port is free**: `lsof -i:10000` should return no results

#### Common Port Commands:
- Find process using port: `lsof -i:10000`
- Kill specific port: `lsof -ti:10000 | xargs kill -9`
- Kill all Flask processes: `pkill -f flask`
- Check all Python processes: `ps aux | grep python`

This prevents the "Port in use" error and eliminates the need for manual port cleanup.

## Maintenance Instructions

### Documentation Updates Required When:
1. **Adding new routes/endpoints**: Update `PROJECT_DOCUMENTATION.md` with new URL patterns, HTTP methods, and descriptions
2. **Modifying existing routes**: Update documentation with changed functionality
3. **Adding new blueprints**: Document the new blueprint structure and all its routes
4. **Database changes**: Update model descriptions in documentation
5. **New features**: Add feature overview and relevant route information

### Update Process:
1. Make code changes
2. Update `PROJECT_DOCUMENTATION.md` with new/changed routes
3. Update this `CLAUDE.md` file if development patterns change
4. Test all functionality
5. **ALWAYS commit changes automatically with descriptive commit message at the end of each session**

## Important File Locations

### Configuration
- Environment variables in `.env` (not in repository)
- Flask config in `app/config.py`
- Database URL and secret keys in environment
- **Python dependencies in `requirements.txt` - MUST be updated when adding new imports**

### Templates
- Base template: `app/templates/base.html`
- Admin templates: `app/templates/admin/`
- Email templates: `app/templates/emails/`

### Static Assets
- CSS: `app/static/styles.css`
- JavaScript: `app/static/script.js`
- Images: `app/static/images/`
- Company logos: `app/static/images/` (named by company)

### External Integrations
- Telegram bot: `telegram_bot.py`
- Email system: `app/send_mail.py`
- Scheduler: `scheduler_config.py`

## Common Tasks

### Adding a New Route
1. Identify the appropriate blueprint file
2. Add route function with proper decorators
3. Create template if needed
4. Update `PROJECT_DOCUMENTATION.md`
5. Test functionality

### Database Changes
1. Modify models in `app/models.py`
2. Generate migration: `flask db migrate -m "description"`
3. Review migration file
4. Apply migration: `flask db upgrade`
5. Update documentation

### Admin Features
- Use `@admin_required` decorator
- Follow existing admin panel patterns
- Place templates in `app/templates/admin/`
- Update admin navigation if needed

## Current Feature Status
- ✅ User authentication with Google OAuth
- ✅ Coupon CRUD with image upload
- ✅ Marketplace with buy/sell functionality
- ✅ Transaction management system
- ✅ Admin panel with user management
- ✅ Newsletter system
- ✅ Telegram bot integration
- ✅ Coupon sharing system
- ✅ Statistics and analytics
- ✅ Email notifications
- ✅ Excel/PDF export functionality

## Project Structure Updates
**IMPORTANT**: When adding new files or directories, update the project structure documentation:

### Project Structure Update Process:
1. **When adding new files/directories**: Always update `project_structure.txt` with the new structure
2. **Use this command** to regenerate the structure: `tree -I '__pycache__|*.pyc|.git|.env|instance|uploads|.DS_Store|sample_text|reports_to_improve' > project_structure.txt`
3. **Before committing**: Ensure `project_structure.txt` reflects current file organization

### Files Excluded from Git:
- `CLAUDE.md` - Internal development instructions
- `PROJECT_DOCUMENTATION.md` - Internal route documentation
- `project_structure.txt` - Auto-generated structure file
- `reports_to_improve/` - Development reports directory
- `git_commits_log.xlsx` - Git tracking Excel file (local project management only)

## Auto-Commit Instructions
**CRITICAL**: At the end of EVERY session, Claude must automatically commit all changes to git with a descriptive commit message. This ensures all work is saved and tracked properly.

### Auto-Commit Process:
1. **Update project structure**: Run `tree -I '__pycache__|*.pyc|.git|.env|instance|uploads|.DS_Store|sample_text|reports_to_improve' > project_structure.txt`
2. Run `git status` to check for changes
3. Add all changes with `git add .`
4. Commit with descriptive message following this format: `git commit -m "Brief description of changes made"`
5. **Update Git tracking Excel file** (see Git Tracking System below)
6. **DO NOT ask for permission** - this should be done automatically

## Git Tracking System
**IMPORTANT**: Every Git commit must be tracked in an Excel file for project management and audit purposes.

### Excel File Setup:
- **File Location**: `git_commits_log.xlsx` in the project root directory
- **NOTE**: This file is added to `.gitignore` and will NOT be committed to the repository (local tracking only)
- **File Structure**: Excel file with the following columns:
  - Column A: **Commit Hash** (first 7 characters)
  - Column B: **Date** (YYYY-MM-DD format)
  - Column C: **Time** (HH:MM format, Israel timezone)
  - Column D: **Commit Message** (full commit message)
  - Column E: **Files Changed** (count of modified files)
  - Column F: **Lines Added** (+X)
  - Column G: **Lines Deleted** (-X)
  - Column H: **Author** (Claude AI)
  - Column I: **Session Type** (Feature/Bug Fix/Maintenance/Documentation)
  - Column J: **Description** (detailed explanation of changes)

### Tracking Process for Each Commit:
1. **After making a Git commit**, immediately update the Excel file
2. **Get commit information**: `git log -1 --stat --pretty=format:"%h|%ad|%s" --date=format:"%Y-%m-%d|%H:%M"`
3. **Extract file statistics**: `git diff --stat HEAD~1 HEAD`
4. **Add a new row** to the Excel file with all the information
5. **Use Python openpyxl** to update the Excel file programmatically

### Required Python Code for Excel Updates:
```python
import openpyxl
from datetime import datetime
import subprocess
import os

def update_git_log_excel():
    # Get commit info
    commit_info = subprocess.check_output(['git', 'log', '-1', '--stat', '--pretty=format:%h|%ad|%s', '--date=format:%Y-%m-%d|%H:%M']).decode('utf-8')
    
    # Parse commit information
    lines = commit_info.split('\n')
    hash_date_msg = lines[0].split('|')
    commit_hash = hash_date_msg[0]
    commit_date = hash_date_msg[1]
    commit_time = hash_date_msg[2]
    commit_message = hash_date_msg[3]
    
    # Count file changes
    files_changed = len([line for line in lines[1:] if '|' in line and ('+++' not in line and '---' not in line)])
    
    # Get line statistics
    stat_info = subprocess.check_output(['git', 'diff', '--stat', 'HEAD~1', 'HEAD']).decode('utf-8')
    lines_added = lines_deleted = 0
    if 'insertions' in stat_info:
        lines_added = int(stat_info.split('insertions')[0].split('+')[-1].strip())
    if 'deletions' in stat_info:
        lines_deleted = int(stat_info.split('deletions')[0].split('-')[-1].strip())
    
    # Update Excel file
    excel_file = 'git_commits_log.xlsx'
    if not os.path.exists(excel_file):
        wb = openpyxl.Workbook()
        ws = wb.active
        headers = ['Commit Hash', 'Date', 'Time', 'Commit Message', 'Files Changed', 'Lines Added', 'Lines Deleted', 'Author', 'Session Type', 'Description']
        ws.append(headers)
    else:
        wb = openpyxl.load_workbook(excel_file)
        ws = wb.active
    
    # Add new row
    new_row = [commit_hash, commit_date, commit_time, commit_message, files_changed, f'+{lines_added}', f'-{lines_deleted}', 'Claude AI', 'Auto-Generated', commit_message]
    ws.append(new_row)
    
    wb.save(excel_file)
```

### Integration with Auto-Commit:
After each `git commit` command, automatically run the Excel update function to maintain a complete log of all project changes. This provides:
- **Project timeline tracking**
- **Development audit trail**  
- **Easy reporting for project management**
- **Visual progress tracking**
- **Integration with project management tools**

Remember: Always keep `PROJECT_DOCUMENTATION.md` synchronized with code changes to maintain accurate route documentation!