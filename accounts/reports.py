"""Reports for one professional over a period (a week, a month or a custom range).

Every report is plain data: a list of KPI tiles plus sections of {title, note, columns, rows}. The same structure feeds the
HTML page and the CSV export, so they can never disagree. Only the signed-in professional's own records are read.

Definitions (also shown on the page):
- patient *seen*: has a Visit dated inside the period.
- *new client*: the patient's very first Visit falls inside the period; *follow-up client*: seen before the period too.
- age is calculated on the last day of the period.
"""
import calendar
import datetime
from collections import Counter

from django.db.models import Min
from django.utils import timezone

from .models import Patient, Visit

AGE_BANDS = [('0-4', 0, 4), ('5-14', 5, 14), ('15-24', 15, 24), ('25-49', 25, 49), ('50-59', 50, 59), ('60+', 60, 200)]
WEEK_START = 6  # Nepal's week starts on Sunday (Python: Monday=0 ... Sunday=6)


def resolve_period(params, today=None):
    """(kind, start, end, label, previous_params, next_params) from the query string. end is inclusive."""
    today = today or timezone.localdate()
    kind = params.get('period', 'month')
    if kind not in ('week', 'month', 'custom'):
        kind = 'month'

    def parse(value, default):
        try:
            return datetime.date.fromisoformat(value)
        except (TypeError, ValueError):
            return default

    if kind == 'week':
        anchor = parse(params.get('date'), today)
        start = anchor - datetime.timedelta(days=(anchor.weekday() - WEEK_START) % 7)
        end = start + datetime.timedelta(days=6)
        prev = {'period': 'week', 'date': (start - datetime.timedelta(days=7)).isoformat()}
        nxt = {'period': 'week', 'date': (start + datetime.timedelta(days=7)).isoformat()}
        label = f'Week of {start:%b} {start.day} - {end:%b} {end.day}, {end.year}'
    elif kind == 'month':
        raw = params.get('month', '')
        try:
            year, month = (int(x) for x in raw.split('-'))
            start = datetime.date(year, month, 1)
        except (ValueError, TypeError):
            start = today.replace(day=1)
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        before, after = start - datetime.timedelta(days=1), end + datetime.timedelta(days=1)
        prev = {'period': 'month', 'month': f'{before:%Y-%m}'}
        nxt = {'period': 'month', 'month': f'{after:%Y-%m}'}
        label = f'{start:%B %Y}'
    else:
        end = parse(params.get('end'), today)
        start = parse(params.get('start'), end - datetime.timedelta(days=29))
        if start > end:
            start, end = end, start
        if (end - start).days > 730:  # keep queries sensible
            start = end - datetime.timedelta(days=730)
        prev = nxt = None
        label = f'{start:%b} {start.day}, {start.year} - {end:%b} {end.day}, {end.year}'
    return kind, start, end, label, prev, nxt


def _bounds(start, end):
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.datetime.combine(start, datetime.time.min), tz)
    hi = timezone.make_aware(datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min), tz)
    return lo, hi


def _age_on(dob, day):
    return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


def _pct(part, whole):
    return f'{round(100 * part / whole)}%' if whole else '-'


def _section(title, columns, rows, note=''):
    return {'title': title, 'columns': columns, 'rows': rows, 'note': note, 'empty': not rows}


def build_report(profile, start, end):
    """The full report for [start, end] (inclusive)."""
    from exercises.models import Prescription, PrescriptionExercise
    from profiles.models import AidEntry, LabEntry, MedicineEntry

    lo, hi = _bounds(start, end)
    patients = profile.workspace_patients()
    visits = Visit.objects.filter(patient__in=patients, date__gte=start, date__lte=end)
    # ---- who was seen, and are they new or follow-up ----
    seen_ids = set(visits.values_list('patient_id', flat=True))
    first_visit = dict(Visit.objects.filter(patient_id__in=seen_ids).values_list('patient_id').annotate(first=Min('date')))
    new_ids = {pid for pid, first in first_visit.items() if first >= start}
    followup_ids = seen_ids - new_ids
    seen = {p.pk: p for p in patients.filter(pk__in=seen_ids)}

    kpis = [
        ('Patients seen', len(seen_ids)), ('Visits / sessions', visits.count()),
        ('New clients', len(new_ids)), ('Follow-up clients', len(followup_ids)),
        ('Patients registered', patients.filter(created_at__gte=lo, created_at__lt=hi).count()),
    ]

    sections = []

    # ---- day by day ----
    visits_by_day = Counter(visits.values_list('date', flat=True))
    new_by_day = Counter(timezone.localtime(d).date() for d in patients.filter(created_at__gte=lo, created_at__lt=hi).values_list('created_at', flat=True))
    rows, day = [], start
    while day <= end:
        rows.append([f'{day:%a %d %b}', visits_by_day.get(day, 0), new_by_day.get(day, 0)])
        day += datetime.timedelta(days=1)
    sections.append(_section('Day by day', ['Day', 'Visits', 'Patients registered'], rows))

    # ---- HMIS-style age x sex tables ----
    def age_sex(ids):
        grid = {label: Counter() for label, _, _ in AGE_BANDS}
        unknown = Counter()
        for pid in ids:
            p = seen[pid]
            sex = p.gender if p.gender in ('M', 'F', 'O') else 'O'
            if not p.date_of_birth:
                unknown[sex] += 1
                continue
            age = _age_on(p.date_of_birth, end)
            for label, low, high in AGE_BANDS:
                if low <= age <= high:
                    grid[label][sex] += 1
                    break
        rows = [[label, c['M'], c['F'], c['O'], sum(c.values())] for label, c in grid.items()]
        if unknown:
            rows.append(['Age not recorded', unknown['M'], unknown['F'], unknown['O'], sum(unknown.values())])
        rows.append(['Total'] + [sum(r[i] for r in rows) for i in range(1, 5)])
        return rows

    cols = ['Age group (years)', 'Male', 'Female', 'Other', 'Total']
    sections.append(_section('New clients by age and sex', cols, age_sex(new_ids), 'First-ever visit falls in this period. Aggregated counts only - this is the shape facility (HMIS-style) monthly returns ask for.'))
    sections.append(_section('Follow-up clients by age and sex', cols, age_sex(followup_ids), 'Seen in this period and also before it.'))

    # ---- diagnoses ----
    dx = Counter()
    for pid in seen_ids:
        p = seen[pid]
        key = (p.icd10_code or '').strip().upper(), (p.diagnosis or '').strip()
        if key != ('', ''):
            dx[key] += 1
    rows = [[code or '-', text or '-', n, _pct(n, len(seen_ids))] for (code, text), n in dx.most_common(15)]
    unrecorded = len(seen_ids) - sum(dx.values())
    if unrecorded:
        rows.append(['-', 'No diagnosis recorded', unrecorded, _pct(unrecorded, len(seen_ids))])
    sections.append(_section('Top diagnoses (patients seen)', ['ICD-10', 'Diagnosis', 'Patients', 'Share'], rows,
                             'Counted once per patient. Choose the ICD-10 code when adding a patient so this table groups cleanly.'))

    # ---- visits ----
    types = dict(Visit.SESSION_CHOICES)
    by_type = Counter(visits.values_list('session_type', flat=True))
    sections.append(_section('Visits by type', ['Type', 'Visits'], [[types.get(k, k), n] for k, n in by_type.most_common()]))
    progress = dict(Visit.PROGRESS_CHOICES)
    by_progress = Counter(visits.values_list('progress', flat=True))
    sections.append(_section('Patient progress at visits', ['Progress', 'Visits', 'Share'],
                             [[progress.get(k) if k else 'Not recorded', n, _pct(n, visits.count())] for k, n in by_progress.most_common()]))

    # ---- exercises, aids, labs, medicines, referrals ----
    prescriptions = Prescription.objects.filter(professional=profile, created_at__gte=lo, created_at__lt=hi)
    items = PrescriptionExercise.objects.filter(prescription__in=prescriptions)
    done = items.filter(is_completed=True).count()
    sections.append(_section('Home exercise programme', ['Measure', 'Value'], [
        ['Prescriptions created', prescriptions.count()], ['Exercises prescribed', items.count()],
        ['Exercises ticked done', done], ['Completion rate', _pct(done, items.count())],
    ]))
    aids = AidEntry.objects.filter(patient__in=patients, issued_on__gte=start, issued_on__lte=end)
    labs = LabEntry.objects.filter(patient__in=patients, ordered_on__gte=start, ordered_on__lte=end)
    meds = MedicineEntry.objects.filter(patient__in=patients, start_date__gte=start, start_date__lte=end)
    sections.append(_section('Other clinical activity', ['Measure', 'Count'], [
        ['Aids issued', aids.count()], ['Lab tests ordered', labs.count()], ['Medicines started', meds.count()],
    ]))
    referral = dict(Patient.REFERRAL_CHOICES)
    new_patients = patients.filter(created_at__gte=lo, created_at__lt=hi)
    by_ref = Counter(new_patients.values_list('referral_source', flat=True))
    sections.append(_section('How new patients heard about you', ['Source', 'Patients'],
                             [[referral.get(k) if k else 'Not recorded', n] for k, n in by_ref.most_common()], 'Patients registered in this period.'))

    # ---- snapshot ----
    status = dict(Patient.STATUS_CHOICES)
    snap = Counter(patients.values_list('status', flat=True))
    sections.append(_section('Caseload today (not limited to the period)', ['Status', 'Patients'], [[status[k], snap.get(k, 0)] for k in status] + [['Total', patients.count()]]))

    practice = ' - '.join(x for x in (profile.practice_name, f'Facility code {profile.facility_code}' if profile.facility_code else '') if x)
    return {'kpis': kpis, 'sections': sections, 'practice': practice}


def to_csv_rows(label, report):
    """Flat rows for the CSV export: a title line per section, its header, its rows, a blank line."""
    out = [['Sajhya Health report', label]]
    if report.get('practice'):
        out.append(['Practice', report['practice']])
    out.append([])
    out.append(['Summary'])
    out.extend([k, v] for k, v in report['kpis'])
    out.append([])
    for s in report['sections']:
        out.append([s['title']])
        out.append(s['columns'])
        out.extend(s['rows'])
        out.append([])
    return out
