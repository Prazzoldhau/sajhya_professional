"""Business actions that more than one screen performs. Put side effects here so they cannot drift apart."""
from .models import Visit, VisitTreatment


def record_visit(patient, therapist, date, session_type=Visit.TREATMENT, progress='', notes='', treatments=(), professional=None, recorded_by_role=''):
    """Record that a session happened and move the patient's last-visit date forward (never backwards). Returns the visit."""
    visit = Visit.objects.create(patient=patient, date=date, therapist=therapist, session_type=session_type, progress=progress, notes=notes, recorded_by_role=recorded_by_role)
    for order, t in enumerate(treatments):
        VisitTreatment.objects.create(visit=visit, kind=t['kind'], name=t['name'], dosage=t['dosage'], order=order)
    patient.last_visit = max(d for d in (patient.last_visit, date) if d)
    patient.save(update_fields=['last_visit'])
    patient.touch()
    return visit
