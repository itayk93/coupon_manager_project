# 🎫 Coupon Master - Digital Coupon Management System

<div align="center">

![Coupon Master Logo](app/static/images/logo.png)

**🇮🇱 Advanced Digital Coupon Management Platform for Israeli Market**

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.0.3-green.svg)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-15+-blue.svg)](https://www.postgresql.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![RTL Support](https://img.shields.io/badge/RTL-Hebrew%20Support-orange.svg)]()

[🌐 Live Demo](https://www.couponmasteril.com) • [📚 Documentation](docs/) • [🤖 Telegram Bot](https://t.me/your_bot)

</div>

---

## ⚠️ Important Notice

**🔒 Admin Access Required**: All scraping and data collection features are restricted to administrator accounts only.

**🔬 Research Purpose**: The scraping functionality in this system is implemented solely for research and educational purposes, and is only accessible to authorized administrators.

---

## 🌟 Overview

**Coupon Master** is a comprehensive digital coupon management system specifically designed for the Israeli market. Built with Flask and modern web technologies, it provides users with an intuitive platform to manage, track, and optimize their digital coupons from various Israeli retailers and services.

### ✨ Key Features

🎯 **Smart Coupon Management**
- Track coupon values, expiration dates, and usage
- Automated expiration reminders (30, 7, 1 day alerts)
- Multi-company support with logo integration
- Advanced filtering and search capabilities

📊 **Analytics & Insights**
- Personal savings dashboard
- Usage statistics and trends
- Company-wise coupon distribution
- Monthly and yearly reports

🛒 **Marketplace Integration**
- Buy and sell coupons securely
- User ratings and reviews system
- Transaction management
- Secure payment handling

🤖 **Telegram Bot Integration**
- Real-time notifications
- Quick coupon lookup
- Mobile-friendly interface
- Hebrew language support

📧 **Advanced Email System**
- Scheduled newsletter campaigns
- Expiration reminders
- Custom HTML email templates
- Analytics and tracking

👥 **Multi-User Platform**
- User profiles and preferences
- Admin dashboard
- Role-based access control
- Secure authentication (Google OAuth2)

---

## 🚀 Technologies Used

### Backend
- **Framework:** Flask 3.0.3 with SQLAlchemy ORM
- **Database:** PostgreSQL with advanced indexing
- **Authentication:** Flask-Login + Google OAuth2
- **Email:** Sendinblue API integration
- **File Processing:** Selenium, Playwright for web scraping
- **Task Management:** External Cron Jobs (replaced internal scheduler)

### Frontend
- **Templates:** Jinja2 with RTL Hebrew support
- **Styling:** Bootstrap 4 + Custom CSS with modern design patterns
- **JavaScript:** Vanilla JS with Ajax for dynamic interactions
- **Charts:** Plotly.js for data visualization
- **Responsive:** Mobile-first design approach

### Infrastructure
- **Hosting:** Render.com with automatic deployments
- **Storage:** PostgreSQL with encrypted sensitive data
- **APIs:** RESTful endpoints with token authentication
- **Bot:** Python Telegram Bot API
- **Analytics:** Custom built-in tracking system

---

## 📋 Features Breakdown

### 🎫 Coupon Management
- **Add Coupons:** Manual entry, image upload, or bulk import from Excel
- **Smart Categorization:** Automatic company detection and logo assignment
- **Usage Tracking:** Monitor spending and remaining values
- **Expiration Management:** Automated alerts and status tracking
- **Sharing System:** Share coupons with friends and family

### 🛒 Marketplace
- **Secure Trading:** Buy and sell unused coupons
- **User Verification:** Rating system and transaction history
- **Payment Integration:** Secure transaction processing
- **Dispute Resolution:** Built-in transaction management

### 📊 Analytics Dashboard
- **Personal Statistics:** Savings tracking and usage patterns  
- **Company Insights:** Brand distribution and preferences
- **Trend Analysis:** Monthly/yearly spending patterns
- **Export Options:** PDF reports and Excel exports

### 🤖 Telegram Integration
- **Real-time Notifications:** Expiration alerts and updates
- **Quick Actions:** View coupons, check balances via chat
- **Hebrew Support:** Full RTL language support
- **Mobile Optimized:** Perfect for on-the-go management

### ⚡ Admin Panel
- **User Management:** View, edit, and manage user accounts
- **Company Management:** Add/edit companies and logos
- **Newsletter System:** Create and schedule email campaigns
- **Analytics:** System-wide statistics and reports
- **Content Management:** Manage tags, categories, and settings

---

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.9+
- PostgreSQL 12+
- Git
- Virtual environment tool (venv/virtualenv)

### Local Development Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/coupon-manager.git
   cd coupon-manager
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   Create a `.env` file in the root directory:
   ```env
   # Database
   DATABASE_URL=postgresql://username:password@localhost:5432/coupon_master
   
   # Security
   SECRET_KEY=your-super-secret-key-here
   SECURITY_PASSWORD_SALT=your-password-salt-here
   ENCRYPTION_KEY=your-fernet-encryption-key-here
   
   # Email Service (Sendinblue)
   SIB_API_KEY=your-sendinblue-api-key
   
   # Google OAuth2
   GOOGLE_CLIENT_ID=your-google-client-id
   GOOGLE_CLIENT_SECRET=your-google-client-secret
   
   # Telegram Bot (Optional)
   TELEGRAM_BOT_TOKEN=your-telegram-bot-token
   TELEGRAM_BOT_USERNAME=your-bot-username
   
   # Cron Job API
   CRON_API_TOKEN=your-secure-api-token-for-cron-jobs
   
   # Analytics
   GA_TRACKING_ID=your-google-analytics-id (optional)
   CLARITY_PROJECT_ID=your-clarity-project-id (optional)
   ```

5. **Database Setup**
   ```bash
   flask db upgrade
   ```

6. **Run the Application**
   ```bash
   python wsgi.py
   ```

   The application will be available at `http://127.0.0.1:10000`

### Production Deployment

#### Using Render.com (Recommended)

1. **Connect Repository** to Render.com
2. **Set Environment Variables** in Render dashboard
3. **Configure Build Command:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure Start Command:**
   ```bash
   gunicorn wsgi:app
   ```

The `render.yaml` file contains all deployment configurations.

#### Manual Deployment

1. **Setup Production Database** (PostgreSQL)
2. **Configure Environment Variables** for production
3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Run Database Migrations:**
   ```bash
   flask db upgrade
   ```
5. **Start with Gunicorn:**
   ```bash
   gunicorn -w 4 -b 0.0.0.0:$PORT wsgi:app
   ```

---

## 📡 API Documentation

### Authentication
There are two cron authentication styles in this project:

1) **Admin scheduled-emails cron endpoints** use:
```bash
Authorization: Bearer YOUR_CRON_API_TOKEN
```

2) **Multipass auto-update cron endpoint** uses:
```bash
X-Cron-Secret: YOUR_CRON_API_TOKEN
```

### Endpoints

#### 📧 Send Scheduled Emails
```bash
POST /admin/scheduled-emails/api/cron/send-pending-emails
```
Sends all pending scheduled newsletters.

**Response:**
```json
{
  "success": true,
  "timestamp": "2025-08-28T10:00:00Z",
  "summary": {
    "total_processed": 5,
    "sent_count": 4,
    "failed_count": 1
  },
  "sent_emails": [...],
  "failed_emails": [...],
  "message": "Cron job completed: 4 emails sent successfully, 1 failed"
}
```

#### ⏰ Send Expiration Reminders
```bash
POST /admin/scheduled-emails/api/cron/send-expiration-reminders
```
Sends coupon expiration reminders (30, 7, 1 day alerts).

**Response:**
```json
{
  "success": true,
  "timestamp": "2025-08-28T09:00:00Z",
  "summary": {
    "total_sent": 12,
    "total_failed": 0,
    "reminders_30_days": 5,
    "reminders_7_days": 4,
    "reminders_1_day": 3
  },
  "message": "Expiration reminders completed: 12 sent successfully"
}
```

### Cron Job Setup

Add these to your server's crontab:

```bash
# Send expiration reminders daily at 9:00 AM
0 9 * * * curl -X POST https://yoursite.com/admin/scheduled-emails/api/cron/send-expiration-reminders \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_CRON_API_TOKEN"

# Send scheduled emails every hour
0 * * * * curl -X POST https://yoursite.com/admin/scheduled-emails/api/cron/send-pending-emails \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_CRON_API_TOKEN"
```

### Multipass Auto-Update (GitHub Actions)

This endpoint is meant to be triggered by an external cron (e.g. cron-job.org). By default it **only dispatches** a
GitHub Actions workflow and returns quickly.

#### 1) Server environment variables (required)

Set these on the server (Render dashboard / production environment variables):

```env
CRON_API_TOKEN=your-long-random-token
GITHUB_TOKEN=your-github-pat-with-actions-permissions
```

Notes:
- If you set env vars via a local `.env`, be careful with `#`: many dotenv parsers treat `#` as a comment unless the
  value is quoted. Prefer setting env vars in the hosting provider dashboard, or quote the value.

#### 2) GitHub token permissions (required)

The `GITHUB_TOKEN` above must be a GitHub Personal Access Token that can dispatch workflows on the `scrape_multipass`
repo:
- Needs access to the repo (`itayk93/scrape_multipass` by default).
- Needs Actions permission to dispatch workflows (and optionally read runs to return `run_url`).

#### 3) Optional overrides (only if you changed the workflow repo/name)

```env
MULTIPASS_GH_OWNER=itayk93
MULTIPASS_GH_REPO=scrape_multipass
MULTIPASS_GH_WORKFLOW=scrape.yml
MULTIPASS_GH_REF=main
MULTIPASS_GH_INPUT_KEY=card_number
MULTIPASS_GH_INPUT_SEPARATOR=,
```

#### 4) cron-job.org configuration (recommended)

Create a cron job that calls your production server:

- **URL:** `https://YOUR_DOMAIN/api/cron/update_multipass`
- **Request method:** `POST`
- **Headers:**
  - `X-Cron-Secret: YOUR_CRON_API_TOKEN`
  - (optional) `Content-Type: application/json`
- **Requires HTTP authentication:** off
- **Treat redirects (3xx) as success:** off (recommended)
- **Time zone:** `Asia/Jerusalem` (or whatever you want)

If you want the old “full server-side flow” (poll workflow, download artifacts, update DB), use:

```bash
curl -X POST "https://YOUR_DOMAIN/api/cron/update_multipass?mode=full" \
  -H "X-Cron-Secret: YOUR_CRON_API_TOKEN"
```

#### 5) What you should see

The endpoint response (default mode) includes `run_url` when available. Open it to confirm the workflow started.

---

## 🗂️ Project Structure

```
coupon-manager/
├── app/                          # Main application package
│   ├── __init__.py              # App factory and configuration
│   ├── models.py                # Database models (User, Coupon, etc.)
│   ├── routes/                  # URL routes and views
│   │   ├── admin_routes/        # Admin panel routes
│   │   ├── auth_routes.py       # Authentication routes
│   │   ├── coupons_routes.py    # Coupon management
│   │   ├── profile_routes.py    # User profile management
│   │   └── ...                  # Other route modules
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── admin/              # Admin panel templates
│   │   ├── emails/             # Email templates
│   │   └── ...                 # Other templates
│   ├── static/                  # Static files (CSS, JS, images)
│   │   ├── css/                # Stylesheets
│   │   ├── js/                 # JavaScript files
│   │   └── images/             # Images and logos
│   ├── analytics/              # Analytics and reporting
│   ├── helpers.py              # Utility functions
│   └── config.py               # Configuration settings
├── migrations/                  # Database migration files
├── docs/                       # Documentation
├── scripts/                    # Utility scripts
├── telegram_bot.py             # Telegram bot implementation
├── wsgi.py                     # WSGI entry point
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `SECRET_KEY` | Flask secret key | Yes |
| `SECURITY_PASSWORD_SALT` | Password hashing salt | Yes |
| `ENCRYPTION_KEY` | Fernet encryption key | Yes |
| `SIB_API_KEY` | Sendinblue API key | Yes |
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID | Optional |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret | Optional |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Optional |
| `CRON_API_TOKEN` | API token for cron jobs | Yes |
| `GA_TRACKING_ID` | Google Analytics ID | Optional |

### Database Schema

The application uses PostgreSQL with the following main tables:
- **users**: User accounts and profiles
- **coupon**: Digital coupons with encryption
- **companies**: Supported retailers and services
- **transactions**: Marketplace transactions
- **newsletters**: Email campaigns and templates
- **newsletter_sendings**: Email delivery tracking

---

## 🛡️ Security

### Data Protection
- **Encryption**: Sensitive data encrypted using Fernet
- **Authentication**: Secure session management with Flask-Login
- **CSRF Protection**: Cross-site request forgery prevention
- **SQL Injection**: Protected via SQLAlchemy ORM
- **XSS Protection**: Template auto-escaping enabled

### Security Best Practices
- Regular security audits
- Dependency updates
- Secure environment variable management
- HTTPS enforcement in production
- Rate limiting on sensitive endpoints

### Reporting Vulnerabilities
If you discover a security vulnerability, please email security@couponmasteril.com instead of opening a public issue.

---

## 📊 Performance

### Database Optimization
- **Indexes**: Strategic indexing on frequently queried columns
- **Query Optimization**: Efficient queries with proper joins
- **Connection Pooling**: PostgreSQL connection management
- **Pagination**: Large datasets handled with pagination

### Caching Strategy
- **Static Files**: CDN caching for assets
- **Database Queries**: Query result caching
- **Template Rendering**: Jinja2 template caching
- **API Responses**: Response caching where appropriate

---

## 🌍 Internationalization

### Hebrew Support
- **RTL Layout**: Complete right-to-left layout support
- **Hebrew Fonts**: Optimized Hebrew typography
- **Date/Time Formatting**: Israeli locale formatting
- **Currency**: Israeli Shekel (₪) support

### Adding Languages
To add support for additional languages:
1. Create translation files in `app/translations/`
2. Update templates with translation markers
3. Configure Flask-Babel
4. Test RTL/LTR layout compatibility

---

## 📈 Analytics & Monitoring

### Built-in Analytics
- User engagement tracking
- Coupon usage patterns
- Conversion rate monitoring
- Performance metrics

### External Integrations
- Google Analytics (optional)
- Microsoft Clarity (optional)
- Custom event tracking
- Error monitoring

---

## 🤖 Telegram Bot Features

### User Commands
- `/start` - Initialize bot connection
- `/coupons` - List your coupons
- `/balance` - Check total coupon value
- `/expiring` - View expiring coupons
- `/help` - Get help and commands list

### Notifications
- Expiration alerts
- New coupon confirmations
- Transaction updates
- System announcements








<div align="center">

**Made with ❤️ for the Israeli Community**

⭐ Star this repo if you find it useful!

[🌐 Website](https://www.couponmasteril.com) • [📧 Contact](mailto:info@couponmasteril.com) • [🤖 Bot](https://t.me/your_bot)

</div>
