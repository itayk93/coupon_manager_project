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
6. Test both functionality and security

### When Modifying Existing Code
1. Check `PROJECT_DOCUMENTATION.md` for current route information
2. Maintain existing URL patterns and HTTP methods
3. Preserve authentication decorators and permissions
4. Update documentation after changes
5. Consider backward compatibility

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

### Testing & Deployment
- Test all routes after modifications
- Check both authenticated and unauthenticated access
- Verify admin functionality separately
- Run migrations before deployment
- Check static file serving

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
5. Commit changes with descriptive commit message

## Important File Locations

### Configuration
- Environment variables in `.env` (not in repository)
- Flask config in `app/config.py`
- Database URL and secret keys in environment

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

Remember: Always keep `PROJECT_DOCUMENTATION.md` synchronized with code changes to maintain accurate route documentation!