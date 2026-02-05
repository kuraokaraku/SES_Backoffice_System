# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Setup (first time)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate

# Run development server
python manage.py runserver

# Run tests
python manage.py test

# Create new migration after model changes
python manage.py makemigrations
python manage.py migrate

# Create superuser for admin access
python manage.py createsuperuser
```

## Architecture Overview

This is a Django 4.2 application for managing freelancer/business partner contracts and monthly work processing.

### Project Structure

- `office_system/` - Django project configuration (settings, URLs, WSGI/ASGI)
- `system_app/` - Main application containing all business logic
  - `models.py` - Database models (Freelancer, BusinessPartner, MonthlyProcess, TaskStatus, PurchaseOrder, BusinessCard)
  - `views.py` - HTTP request handlers with login_required protection
  - `forms.py` - Django forms for validation
  - `services/` - External integrations (email_service.py for IMAP, sync_service.py for spreadsheet import)
  - `templates/` - HTML templates using Bootstrap 5.3

### Key Models

- **Freelancer/BusinessPartner**: Contractor information with pricing rules (base unit price, hour limits, overtime/deduction rates)
- **MonthlyProcess**: Tracks monthly processing periods (year_month format: "YYYY-MM")
- **TaskStatus**: Links freelancers to monthly processes with working hours and auto-calculated payment amounts
- **PurchaseOrder**: Stores downloaded purchase order PDFs with client association

### Business Logic

- Payment calculation in `TaskStatus.calculate_amount()` applies pricing rules based on working hours vs. hour limits
- Email service uses IMAP to search XServer mailbox for purchase orders by client name and date range
- Views use `@login_required` decorator; admin functions check `is_superuser`

### Environment Variables

Configuration in `.env` file (never commit):
- `SECRET_KEY`, `DEBUG`
- `XSERVER_IMAP_SERVER`, `XSERVER_MAIL_USER`, `XSERVER_MAIL_PASSWORD` (for PO email sync)

### URLs

- `/` - Login page
- `/menu/` - Main dashboard (requires login)
- `/admin/` - Django admin interface
- `/party/` - Unified freelancer/partner list
- `/monthly/` - Monthly processing views
- `/purchase_orders/` - Purchase order management
