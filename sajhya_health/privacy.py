"""What the platform operator can open through the Django admin.

Professionals' patient records (who the patients are, their notes, bills, packages, exercises, assessments and lab entries) are not registered in the admin at all:
there is no page to browse them. The operator keeps accounts, the exercise library and the medicine and lab catalogues.
Support work on a workspace uses /support/, which shows patient codes and counts and never names, phone numbers or note text.

ADMIN_SHOW_PATIENT_DATA=True puts them back (for a rare repair). That is a deliberate bypass: every admin page staff open is written to the access log
the professional reads, and the setting is visible in the server's .env, so use it only with the professional's knowledge.
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.sites import NotRegistered

# (app label, model name) of every model that holds patient identity or clinical data
PATIENT_DATA = [
    ('accounts', 'Patient'), ('accounts', 'Visit'), ('accounts', 'VisitTreatment'), ('accounts', 'TreatmentPlan'),
    ('accounts', 'PlanGoal'), ('accounts', 'PlanMeasure'), ('accounts', 'PlanReading'), ('accounts', 'PlanPhase'), ('accounts', 'PlanItem'),
    ('assessments', 'AssessmentSession'), ('assessments', 'AssessmentResult'), ('assessments', 'ClinicalRecord'),
    ('exercises', 'Prescription'), ('exercises', 'PrescriptionExercise'), ('exercises', 'ExerciseFeedback'),
    ('profiles', 'PatientProfile'), ('profiles', 'MedicineEntry'), ('profiles', 'NursingEntry'), ('profiles', 'AidEntry'), ('profiles', 'TherapyNote'), ('profiles', 'LabEntry'),
    ('soapnotes', 'SoapNote'), ('soapnotes', 'SoapAddendum'), ('soapnotes', 'SoapShare'),
]


def hide_patient_data():
    if getattr(settings, 'ADMIN_SHOW_PATIENT_DATA', False):
        return
    from django.apps import apps
    for label, name in PATIENT_DATA:
        try:
            model = apps.get_model(label, name)
        except LookupError:
            continue
        try:
            admin.site.unregister(model)
        except NotRegistered:
            pass
