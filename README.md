# ParkIT

**Course**: IT317-G1 CSIT327-G7

**Title**: CIT-U Car Parking Management System


## Executive Summary
ParkIT! is a web-based Car Parking Management System designed to improve the 
efficiency of parking operations within Cebu Institute of Technology – University (CIT-U). 
The system provides real-time monitoring of available and occupied slots, structured 
vehicle entry/exit logging, and role-based user management for administrators and 
attendants. Unlike manual or sticker-based methods, it offers transparency, accessibility, 
and reliable record-keeping to reduce congestion and wasted time in the campus 
parking areas.

## Tech Stack
backend: Django (Python)
Database: Supabase
Frontend: Django Templates + HTML + CSS
Deployment: Render (backend + Frontend), Supabase(database)

# Environment Setup
**1. Create a .env File**

In the project root directory (same level as `manage.py`), create a file named `.env`.

**2. Add Supabase Credentials**

Insert your Supabase credentials inside `.env`:

### env
SUPABASE_URL=your-supabase-url
SUPABASE_KEY=your-supabase-anon-or-service-key

**3. Install Python Dependencies**

**Activate virtual environment (Windows):**

`venv\Scripts\activate`

**Install requirements:**

`pip install -r requirements.txt`

**4. Run Local Server**

`python manage.py runserver`

# Team Members
**Ramirez, Ruther Gerard** - Product Owner - [ruthergerard.ramirez@cit.edu]()

**Pacio, Muriel** - Business Analyst - [muriel.pacio@cit.edu]()

**Panonce, Herlanz Mirby** - Scrum Master - [herlanzmirby.panonce@cit.edu]()

**Lawas, Berchard Lawrence** - Lead Developer - [berchardlawrence.lawas@cit.edu]()

**Loy, Andrei Sam** - Back-end Developer - [andreisam.loy@cit.edu]()

**Lo, Joshua Noel** - Front-end Developer - [joshuanoel.lo@cit.edu]()