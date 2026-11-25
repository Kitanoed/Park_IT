# ParkIT

**ParkIT** is a web-based parking management system for Cebu Institute of Technology–University (CIT-U). It helps campus staff monitor parking availability, record vehicle entry and exit, and manage parking operations through role-based administrator and attendant interfaces.

## Overview

ParkIT replaces manual parking workflows with a shared system for viewing lot occupancy and maintaining parking activity records. Administrators can manage users, parking spaces, and reports, while attendants can use the operational dashboard to support day-to-day parking activity.

## Features

- Parking lot and space availability views
- Vehicle check-in and check-out tracking
- Administrator and attendant dashboards
- User management, account status controls, and password reset flows
- Parking history with filtering and pagination
- Reports, including CSV export and monthly summaries
- Profile and password management

## Technology

- **Backend:** Python 3.11, Django 5.2
- **Frontend:** Django templates, HTML, CSS, and JavaScript
- **Data services:** Supabase; SQLite is used as the local database fallback
- **Production server:** Gunicorn
- **Deployment:** Render

## Prerequisites

- Python 3.11
- pip
- A Supabase project and its project URL and API key

## Local Development

1. Clone the repository and enter the project directory:

   ```bash
   git clone https://github.com/Kitanoed/Park_IT.git
   cd Park_IT
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell, activate it with:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

3. Install the project dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Create a `.env` file in the repository root and add your Supabase configuration:

   ```dotenv
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_ANON_KEY=your-supabase-anon-key
   ```

   The application also accepts `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_KEY` as the Supabase key. Keep all credentials private; do not commit real secrets to the repository.

5. Apply Django migrations and start the development server:

   ```bash
   python manage.py migrate
   python manage.py runserver
   ```

   Open <http://127.0.0.1:8000/> in your browser.

## Tests

Run the Django test suite with:

```bash
python manage.py test
```

## Deployment

The repository includes a `Procfile` configured to run the Django application with Gunicorn:

```text
web: gunicorn Park_IT.wsgi
```

For a Render deployment, configure the required Supabase environment variables in the service settings. When using a hosted Django database, configure `DATABASE_URL` as well. Never place production credentials in source control.

## Project Structure

```text
Park_IT/                    # Django project configuration, routes, views, and forms
  settings.py
  urls.py
  views.py
  models.py
templates/                  # Django HTML templates
static/                     # Static assets
utils/                      # Supabase client and shared utilities
manage.py                   # Django management commands
requirements.txt            # Python dependencies
Procfile                    # Production web process
PARKING_HISTORY_API_SPEC.md # Parking history API specification
```

## API Reference

The administrator parking-history API and its query parameters are documented in [PARKING_HISTORY_API_SPEC.md](PARKING_HISTORY_API_SPEC.md).

## License

No license is currently specified for this repository. Contact the project owner for permission before redistribution or other reuse.