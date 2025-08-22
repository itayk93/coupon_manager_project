# Coupon Manager Project - Complete Documentation

## Project Overview
This is a Flask-based web application for managing coupons, featuring a marketplace system, user authentication, admin panel, Telegram integration, and comprehensive analytics. The system allows users to buy, sell, and share coupons while providing administrative tools for management.

## Project Structure
```
coupon_manager_project/
├── app.py                          # Main Flask application entry point
├── wsgi.py                        # WSGI configuration for deployment  
├── app/
│   ├── __init__.py               # Application factory and configuration
│   ├── config.py                 # Configuration settings
│   ├── extensions.py             # Flask extensions initialization
│   ├── models.py                 # Database models
│   ├── forms.py                  # WTForms definitions
│   ├── helpers.py                # Helper functions
│   ├── send_mail.py             # Email functionality
│   └── routes/                   # Route blueprints
├── migrations/                   # Database migration files
├── static/                      # Static assets (CSS, JS, images)
├── templates/                   # Jinja2 templates
└── uploads/                     # File upload directory
```

---

## Complete URL Routes and Endpoints Documentation

### 1. Authentication Routes (`/auth/*`)
**Blueprint:** `auth_bp` (prefix: `/auth`)
**File:** `app/routes/auth_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/auth/login/google` | GET | `login_google` | Redirects user to Google OAuth login page |
| `/auth/register/google` | GET | `register_google` | Redirects user to Google OAuth registration page |
| `/auth/login/google/authorized` | GET | `google_callback` | Handles callback from Google OAuth authentication |
| `/auth/confirm/<token>` | GET | `confirm_email` | Email confirmation endpoint using unique token |
| `/auth/login` | GET, POST | `login` | User login page with form submission |
| `/auth/register` | GET, POST | `register` | User registration page with form validation |
| `/auth/logout` | GET | `logout` | User logout endpoint (requires authentication) |
| `/auth/save_consent` | POST | `save_consent` | Saves user consent for data processing compliance |
| `/auth/privacy-policy` | GET | `privacy_policy` | Displays privacy policy page |
| `/auth/forgot_password` | GET, POST | `forgot_password` | Password reset request form |
| `/auth/reset_password/<token>` | GET, POST | `reset_password` | Password reset form with secure token validation |

### 2. Profile Routes (`/profile/*` or `/`)
**Blueprint:** `profile_bp` (no prefix)
**File:** `app/routes/profile_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/` | GET | `home` | Homepage with authentication check and redirect logic |
| `/faq` | GET | `faq` | Frequently Asked Questions page |
| `/index` | GET, POST | `index` | Main user dashboard/profile page with coupon overview |
| `/load_stats_modal` | GET | `load_stats_modal` | AJAX endpoint to load statistics modal data |
| `/dismiss_expiring_alert` | GET | `dismiss_expiring_alert` | Dismisses coupon expiration alert notifications |
| `/notifications` | GET | `notifications` | User notification center page |
| `/delete_notification/<int:notification_id>` | POST | `delete_notification` | Deletes specific notification by ID |
| `/delete_all_notifications` | POST | `delete_all_notifications` | Removes all user notifications |
| `/update_profile_field` | POST | `update_profile_field` | AJAX endpoint for profile field updates |
| `/about` | GET | `about` | About page with application information |
| `/buy_slots` | GET, POST | `buy_slots` | Purchase additional coupon slots functionality |
| `/edit_profile` | GET, POST | `edit_profile` | Profile editing form with validation |
| `/rate_user/<int:user_id>/<int:transaction_id>` | GET, POST | `rate_user` | User rating system after transactions |
| `/user_profile/<int:user_id>` | GET, POST | `user_profile` | View specific user's public profile |
| `/user_profile` | GET | `user_profile_default` | Default user profile redirect |
| `/landing_page` | GET | `landing_page` | Public landing page for non-authenticated users |
| `/change_password` | GET, POST | `change_password` | Password change form for authenticated users |
| `/confirm_password_change/<token>` | GET | `confirm_password_change` | Confirms password change via email token |
| `/connect_telegram` | GET | `connect_telegram` | Telegram bot connection setup |
| `/preferences` | GET, POST | `user_preferences` | User preferences and settings page |
| `/unsubscribe` | GET | `unsubscribe_newsletter` | Newsletter unsubscription page |
| `/complete_unsubscribe` | GET | `complete_unsubscribe` | Completes newsletter unsubscription process |
| `/complete_preferences` | GET | `complete_preferences` | Completes preferences update from email |
| `/preferences_from_email` | GET | `preferences_from_email` | Updates preferences directly from email link |

### 3. Coupon Routes (`/coupons/*`)
**Blueprint:** `coupons_bp` (prefix: `/coupons`)
**File:** `app/routes/coupons_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/coupons/` | GET | `coupons` | Main coupons listing page with filters |
| `/coupons/add` | GET, POST | `add_coupon` | Add new coupon form |
| `/coupons/add_with_image` | GET, POST | `add_coupon_with_image` | Add coupon with image upload |
| `/coupons/edit/<int:id>` | GET, POST | `edit_coupon` | Edit existing coupon details |
| `/coupons/delete/<int:id>` | POST | `delete_coupon` | Delete coupon (soft delete) |
| `/coupons/detail/<int:id>` | GET | `coupon_detail` | Detailed coupon view |
| `/coupons/sell/<int:id>` | GET, POST | `sell_coupon` | List coupon for sale in marketplace |
| `/coupons/update_usage/<int:id>` | GET, POST | `update_coupon_usage` | Update coupon usage tracking |
| `/coupons/mark_fully_used/<int:id>` | POST | `mark_coupon_as_fully_used` | Mark coupon as completely used |
| `/coupons/quick_add` | POST | `quick_add_coupon` | AJAX quick coupon addition |

### 4. Marketplace Routes (`/marketplace/*`)
**Blueprint:** `marketplace_bp` (prefix: `/marketplace`)
**File:** `app/routes/marketplace_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/marketplace` | GET | `marketplace` | Main marketplace listing with search/filter |
| `/marketplace/coupon/<int:id>` | GET | `marketplace_coupon_detail` | Detailed view of coupon in marketplace |
| `/request_coupon/<int:id>` | GET, POST | `request_coupon_detail` | Request specific coupon details |
| `/coupon_request/<int:id>` | GET, POST | `coupon_request_detail_view` | View coupon request details |
| `/delete_coupon_request/<int:id>` | POST | `delete_coupon_request` | Delete coupon request |
| `/seller_cancel_transaction/<int:transaction_id>` | GET | `seller_cancel_transaction` | Seller cancels active transaction |
| `/review_seller/<int:seller_id>` | GET, POST | `review_seller` | Leave review for seller after transaction |
| `/offer_coupon/<int:request_id>` | GET, POST | `offer_coupon_selection` | Offer coupon selection interface |
| `/offer_coupon_process/<int:request_id>` | POST | `offer_coupon_process` | Process coupon offer submission |
| `/transaction_about` | GET | `transaction_about` | Information about transaction process |

### 5. Request Routes (`/requests/*`)
**Blueprint:** `requests_bp` (prefix: `/requests`)
**File:** `app/routes/requests_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/requests/coupon_request/<int:id>` | GET, POST | `coupon_request_detail` | Detailed view of coupon request |
| `/requests/delete_coupon_request/<int:id>` | POST | `delete_coupon_request` | Delete specific coupon request |
| `/requests/request_coupon` | GET, POST | `request_coupon` | Create new coupon request |
| `/requests/buy_slots` | GET, POST | `buy_slots` | Purchase additional request slots |

### 6. Transaction Routes (`/transactions/*`)
**Blueprint:** `transactions_bp` (prefix: `/transactions`)
**File:** `app/routes/transactions_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/transactions/my_transactions` | GET | `my_transactions` | User's transaction history and status |
| `/transactions/buy_coupon` | POST | `buy_coupon` | Initialize coupon purchase process |
| `/transactions/approve_transaction/<int:transaction_id>` | GET, POST | `approve_transaction` | Seller approves transaction |
| `/transactions/decline_transaction/<int:transaction_id>` | GET | `decline_transaction` | Seller declines transaction |
| `/transactions/confirm_transaction/<int:transaction_id>` | GET | `confirm_transaction` | Buyer confirms transaction completion |
| `/transactions/cancel_transaction/<int:transaction_id>` | GET | `cancel_transaction` | Buyer cancels pending transaction |
| `/transactions/mark_coupon_as_fully_used/<int:id>` | POST | `mark_coupon_as_fully_used` | Mark purchased coupon as fully used |
| `/transactions/update_coupon/<int:id>` | GET, POST | `update_coupon` | Update coupon usage details |
| `/transactions/update_all_coupons` | GET | `update_all_coupons` | Bulk update all active coupons |
| `/transactions/complete_transaction/<int:transaction_id>` | GET | `complete_transaction_route` | Admin complete transaction |
| `/transactions/seller_confirm_transfer/<int:transaction_id>` | GET, POST | `seller_confirm_transfer` | Seller confirms payment received |
| `/transactions/seller_add_coupon_code/<int:transaction_id>` | GET, POST | `seller_add_coupon_code` | Add coupon code to transaction |
| `/transactions/buyer_confirm_transfer/<int:transaction_id>` | GET, POST | `buyer_confirm_transfer` | Buyer confirms payment sent |
| `/transactions/buy_coupon_direct` | GET | `buy_coupon_direct` | Direct coupon purchase from email |

### 7. Export Routes (`/export/*`)
**Blueprint:** `export_bp` (prefix: `/export`)
**File:** `app/routes/export_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/export/export_excel` | GET | `export_excel` | Export user coupons to Excel format |
| `/export/export_pdf` | GET | `export_pdf` | Export user coupons to PDF format |

### 8. Upload Routes (`/uploads/*`)
**Blueprint:** `uploads_bp` (prefix: `/uploads`)
**File:** `app/routes/uploads_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/uploads/upload_coupons` | GET, POST | `upload_coupons` | Bulk upload coupons from Excel file |
| `/uploads/add_coupons_bulk` | GET, POST | `add_coupons_bulk` | Manual bulk addition of multiple coupons |
| `/uploads/download_template` | GET | `download_template` | Download Excel template for coupon upload |

### 9. Admin Main Routes (`/admin/*`)
**Blueprint:** `admin_bp` (prefix: `/admin`)
**File:** `app/routes/admin_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/admin/update_coupon_transactions` | POST | `update_coupon_transactions` | Update coupon transaction data |
| `/admin/manage_users` | GET | `manage_users` | User management interface |
| `/admin/reset_user_password` | POST | `reset_user_password` | Admin password reset for users |
| `/admin/feature_access` | GET, POST | `manage_feature_access` | Manage user feature access permissions |

### 10. Admin Dashboard Routes (`/admin/dashboard/*`)
**Blueprint:** `admin_dashboard_bp` (prefix: `/admin`)
**File:** `app/routes/admin_routes/admin_dashboard_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/admin/dashboard_coupons` | GET | `dashboard` | Admin analytics and statistics dashboard |

### 11. Admin Users Management (`/admin/users/*`)
**File:** `app/routes/admin_routes/admin_users_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/admin/users/` | GET | `manage_users` | Admin user management interface |
| `/admin/users/reset_password` | POST | `reset_user_password` | Admin initiated password reset |
| `/admin/users/update_slots_automatic_coupons` | POST | `update_slots_automatic_coupons` | Update user coupon slots |
| `/admin/users/initiate_delete_user` | POST | `initiate_delete_user` | Begin user deletion process |
| `/admin/users/confirm_delete_user/<token>` | GET | `confirm_delete_user` | Confirm user deletion with token |
| `/admin/users/resend_confirmation_email` | POST | `resend_confirmation_email` | Resend user email confirmation |

### 12. Admin Newsletter Management (`/admin/newsletter/*`)
**Blueprint:** `admin_newsletter_bp` (prefix: `/admin/newsletter`)
**File:** `app/routes/admin_routes/admin_newsletter_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/admin/newsletter/manage` | GET | `manage_newsletters` | Newsletter management dashboard |
| `/admin/newsletter/create` | GET, POST | `create_newsletter` | Create new newsletter |
| `/admin/newsletter/edit/<int:newsletter_id>` | GET, POST | `edit_newsletter` | Edit existing newsletter |
| `/admin/newsletter/preview/<int:newsletter_id>` | GET | `preview_newsletter` | Preview newsletter before sending |
| `/admin/newsletter/send/<int:newsletter_id>` | GET, POST | `send_newsletter` | Send newsletter to subscribers |
| `/admin/newsletter/delete/<int:newsletter_id>` | POST | `delete_newsletter` | Delete newsletter |
| `/admin/newsletter/api/users` | GET | `get_users_api` | API endpoint for user data in newsletters |

### 13. Admin Company Management (`/admin/companies/*`)
**Blueprint:** `admin_companies_bp` (prefix: `/admin/companies`)
**File:** `app/routes/admin_routes/admin_companies_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/admin/companies/` | GET, POST | `manage_companies` | Company management interface |
| `/admin/companies/delete_company/<int:company_id>` | POST | `delete_company` | Delete company from system |

### 14. Admin Tag Management (`/admin/tags/*`)
**File:** `app/routes/admin_routes/admin_tags_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/admin/tags/edit_tag/<int:tag_id>` | GET, POST | `edit_tag` | Edit tag properties |
| `/admin/tags/transfer_coupons/<int:source_tag_id>` | GET, POST | `transfer_coupons` | Transfer coupons between tags |
| `/admin/tags/manage` | GET, POST | `manage_tags` | Tag management interface |

### 15. Admin Scheduled Emails Routes (`/admin/scheduled-emails/*`)
**Blueprint:** `admin_scheduled_emails_bp` (prefix: `/admin/scheduled-emails`)
**File:** `app/routes/admin_routes/admin_scheduled_emails_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/admin/scheduled-emails/scheduled-emails` | GET | `scheduled_emails` | View scheduled emails for today with management interface |
| `/admin/scheduled-emails/send-pending-emails` | POST | `send_pending_emails` | API endpoint to send emails that are past due and haven't been sent |

**Key Features:**
- **Email Scheduling Management**: View all emails scheduled to be sent today with their status
- **Pending Email Delivery**: Send emails that are past their scheduled time but haven't been sent yet
- **Real-time Status Tracking**: Track which emails have been sent, are pending, or are scheduled for future
- **Cron Job Integration**: API endpoint designed for hourly cron job execution
- **Admin Access Only**: All routes require admin authentication

**API Details for Cron Job:**
- **URL**: `POST /admin/scheduled-emails/send-pending-emails`
- **Purpose**: Send emails that are past their scheduled time but haven't been sent
- **Behavior**: Only sends emails where `scheduled_send_time <= current_time` and `is_sent = False`
- **Response**: JSON with sent/failed email counts and details
- **Recommended Schedule**: Every hour via cron job

### 17. Telegram Bot Routes (`/telegram/*`)
**Blueprint:** `telegram_bp` (prefix: `/telegram`)
**File:** `app/routes/telegram_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/telegram/bot` | GET | `telegram_bot_page` | Telegram bot information and setup page |
| `/telegram/connect_telegram` | GET | `connect_telegram` | Connect user account to Telegram bot |
| `/telegram/generate_token` | POST | `generate_token` | Generate verification token for Telegram |
| `/telegram/verify_telegram` | POST | `verify_telegram` | Verify Telegram connection |
| `/telegram/api/telegram_coupons` | POST | `get_telegram_coupons` | API endpoint for Telegram bot coupon access |

### 18. Statistics Routes (`/statistics/*`)
**Blueprint:** `statistics_bp` (prefix: `/statistics`)
**File:** `app/routes/statistics_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/statistics/` | GET | `statistics_page` | Statistics and analytics dashboard |
| `/statistics/api/data` | GET | `get_statistics_data` | API endpoint for statistics data |

### 19. Sharing Routes (`/sharing/*`)
**Blueprint:** `sharing_bp` (no prefix)
**File:** `app/routes/sharing_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/generate_share_link/<int:coupon_id>` | POST | `generate_share_link` | Generate secure sharing link for coupon |
| `/get_current_share_link/<int:coupon_id>` | GET | `get_current_share_link` | Get current sharing link status |
| `/share_coupon/<token>` | GET | `share_coupon` | Coupon sharing confirmation page |
| `/confirm_share/<token>` | POST | `confirm_share` | Confirm acceptance of shared coupon |
| `/revoke_sharing/<int:share_id>` | POST | `revoke_sharing` | Revoke coupon sharing access |
| `/quick_revoke/<token>` | GET | `quick_revoke` | Quick revoke sharing from email |
| `/track_coupon_viewer/<int:coupon_id>` | POST | `track_coupon_viewer` | Track who views shared coupons |
| `/get_active_viewers/<int:coupon_id>` | GET | `get_active_viewers` | Get list of active coupon viewers |

### 20. Cron/Scheduled Tasks Routes
**Blueprint:** `cron_bp` (no prefix)
**File:** `app/routes/cron_routes.py`

| URL Pattern | HTTP Methods | Function | Description |
|-------------|-------------|----------|-------------|
| `/cron/run-task/A5d8F2gH3jK4lPq9wE7rT1zU0iO` | GET | `cron_task` | Secure cron job endpoint (no authentication required) |
| `/cron/test` | GET | `cron_test` | Cron job testing endpoint |

---

## Key Features Overview

### Authentication & User Management
- **Google OAuth Integration**: Seamless login/registration with Google accounts
- **Email Verification**: Secure email confirmation system
- **Password Management**: Reset and change password functionality
- **User Profiles**: Comprehensive profile management with ratings

### Coupon Management System
- **CRUD Operations**: Full create, read, update, delete functionality for coupons
- **Usage Tracking**: Monitor coupon utilization and remaining value
- **Expiration Alerts**: Automated notifications for expiring coupons
- **Bulk Operations**: Excel import/export and bulk addition capabilities

### Marketplace & Trading
- **Buy/Sell System**: Complete marketplace for coupon trading
- **Request System**: Users can request specific coupons
- **Transaction Management**: Secure transaction workflow with confirmations
- **Rating System**: User feedback and rating system

### Admin Panel
- **User Management**: Complete admin control over user accounts
- **Analytics Dashboard**: Comprehensive statistics and reporting
- **Newsletter System**: Built-in newsletter creation and distribution
- **Company/Tag Management**: Organize coupons by companies and tags

### Integrations
- **Telegram Bot**: Full integration with Telegram for mobile access
- **Email System**: Automated email notifications and newsletters
- **File Processing**: Excel and PDF export/import capabilities

### Security Features
- **CSRF Protection**: Cross-site request forgery protection
- **Secure Tokens**: Token-based authentication for sensitive operations
- **Access Control**: Role-based feature access management
- **Session Management**: Secure session handling with configurable timeouts

---

## Database Models Overview

The application uses SQLAlchemy ORM with the following main entities:

- **User**: User accounts with authentication and profile data
- **Coupon**: Coupon details including value, company, usage tracking
- **Transaction**: Buy/sell transactions between users
- **Company**: Coupon issuing companies
- **Tag**: Coupon categorization system
- **Newsletter**: Newsletter content and distribution
- **CouponSharing**: Coupon sharing between users
- **Notification**: User notification system

---

## Technical Stack

- **Backend**: Flask (Python web framework)
- **Database**: SQLAlchemy ORM with SQLite/PostgreSQL
- **Frontend**: Jinja2 templates with Bootstrap CSS
- **Authentication**: Flask-Login with OAuth2 support
- **Task Scheduling**: APScheduler for background tasks
- **Email**: SMTP integration for notifications
- **File Processing**: openpyxl for Excel, ReportLab for PDF
- **Security**: Flask-WTF for CSRF protection
- **Deployment**: WSGI compatible (Gunicorn, uWSGI)

---

## Environment Configuration

Key environment variables:
- `SECRET_KEY`: Flask secret key for session security
- `DATABASE_URL`: Database connection string
- `SECURITY_PASSWORD_SALT`: Password hashing salt
- `GA_TRACKING_ID`: Google Analytics tracking
- `CLARITY_PROJECT_ID`: Microsoft Clarity analytics

---

This documentation provides a complete overview of all routes, endpoints, and functionality in the Coupon Manager application. Each endpoint is designed to handle specific aspects of coupon management, user interaction, and system administration.