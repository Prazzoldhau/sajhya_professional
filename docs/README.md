# Sajhya Professional - documentation

> Inherited from Sajhya Health: some pages still mention clinics, billing, appointments or the patient portal. Those features are not part of this project.

Start here. Everything a person needs to run, understand, fix and extend the project without asking anyone.

| Read this | When |
| --- | --- |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Something is broken or behaves oddly. Organised by what you *see*, with the cause and the fix. |
| [OPERATIONS.md](OPERATIONS.md) | Deploying, updating, backing up, restoring, managing users, reading logs. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | You want to understand how it fits together, or add a feature. Includes recipes. |
| [ASSESSMENTS.md](ASSESSMENTS.md) | Using, adding or changing assessment scales and forms (Barthel, Berg, FIM ...). |
| [DEPLOY_CPANEL.md](DEPLOY_CPANEL.md) | Deploying on cPanel/Passenger without SSH (Terminal + plain git clone): database, Python app, `.env`, deploy script, rollback, lessons from the Dhaubanjar deployment. |
| [SOAP_NOTES.md](SOAP_NOTES.md) | The SOAP note form, locking/addenda, and how a treatment plan starts from a note. |
| [DECISIONS.md](DECISIONS.md) | You wonder *why* something was built a certain way, or what is unfinished. |
| [../README.md](../README.md) | Quick setup and the production checklist. |

## The 60-second picture

- **Django 5.2 + MySQL**, server-rendered pages with a little JavaScript. No front-end build step.
- Apps: `accounts` (users, onboarding, patients, treatment plans), `exercises` (library + prescriptions), `profiles` (patient medicine / nursing / aids / rehab / lab), `assessments` (outcome-measure scales, forms and results), `soapnotes` (SOAP notes), `marketplace` (pharmacy and product catalogue only) and `lab` (lab-test catalogue only), and the project package `sajhya_health`.
- **Who can see what** is decided in one file: `accounts/access.py`. A professional only ever sees their own patients.
- **Tests**: `python manage.py test` (265 tests, ~45 s). `sajhya_health/test_end_to_end.py` walks the whole product; if it
  fails, start there.
- **When something is wrong in production**: look at `/healthz/`, then the log (`logs/sajhya.log`), then
  [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
