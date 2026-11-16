# Sajhya Professional

A Django workspace for **one professional at a time**: a physiotherapist (or other rehabilitation professional) signs up, is verified by staff,
and then keeps their own patients, SOAP notes, assessments, treatment plans and home exercise programmes in one private place.

This project was split from [Sajhya Health](https://github.com/Prazzoldhau/sajhya_health). It keeps only the **professional account**. It has no
clinic accounts, enterprise accounts, client/patient logins, billing, appointments or shop.

| Area | What it does |
| --- | --- |
| **Landing + sign-up** | A short public page; sign up as a professional (choose a profession), 4-step save-and-resume onboarding with private licence uploads, and a staff review queue (approve / reject with a reason). |
| **Dashboard** | Patients to treat, follow-ups due, who was treated today, recent patients, weekly visits. |
| **Patients** | Search, filters, private profile pictures, ICD-10 diagnosis lookup, sessions, notes, documents. |
| **Patient profile** | Medicine (pharmacy catalogue), nursing, surgical aids, rehab, lab tests (lab catalogue). |
| **SOAP notes** | Full S/O/A/P form (pain, red flags, ROM, strength, special tests, ICD-10, goals); draft, finalise (locked) and addenda; PDF and share by WhatsApp or e-mail. |
| **Assessments** | 25 ready-made scales and clinical forms with automatic totals, interpretation and progress over time. |
| **Treatment plans** | Baseline measures, goals, phased interventions and progress readings, printable. |
| **Exercise library** | Exercises by region with pictures and videos; prescribe a home programme and send it as a PDF (English and Nepali). |
| **Messages** | WhatsApp / Viber / SMS messages with your own wording; follow-up notices. |
| **Reports** | Weekly, monthly or custom range: KPIs, new vs follow-up clients by age and sex, top diagnoses, exercise adherence; CSV download. |
| **Security** | Verified-professionals-only workspace, login lockout, access log, idle sign-out, optional two-step sign-in (set `REQUIRE_STAFF_MFA=True` to require it for staff), a support view that shows only counts and patient codes. |

## Local development

```
python -m venv venv
venv\Scriptsctivate            # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # then edit it (DEBUG=True for development)
python manage.py migrate
python manage.py load_icd10 && python manage.py load_exercises && python manage.py load_pharmacy   && python manage.py load_lab_catalog && python manage.py load_catalog && python manage.py load_scales    # reference data (safe to re-run)
python manage.py createsuperuser # staff account: reviews professional applications
python manage.py runserver
```

Tests (they run on in-memory SQLite): `python manage.py test`. `sajhya_health/test_end_to_end.py` follows a professional through the whole product.

## Production

See [`docs/DEPLOY_CPANEL.md`](docs/DEPLOY_CPANEL.md) and [`docs/OPERATIONS.md`](docs/OPERATIONS.md). On the server, after `git pull`, run
`bash deploy/cpanel_deploy.sh` (it backs up the database, migrates, collects static files and restarts the app).

Notes:

- **Exercise pictures**: only part of the image library is in git. Copy the full `static/exercises/` folder to the server separately; exercises whose picture file is missing simply show without one.
- **Documentation**: the files under `docs/` were inherited from Sajhya Health and may still mention clinics, billing or the patient portal. Those parts do not exist here.
- **Time zone** is `Asia/Kathmandu`.
