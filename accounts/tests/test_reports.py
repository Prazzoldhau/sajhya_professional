import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import Visit
from ..reports import build_report, resolve_period
from .helpers import PASSWORD, make_patient, make_professional


class PeriodTests(TestCase):
    def test_week_starts_on_sunday_and_month_covers_all_days(self):
        kind, start, end, *_ = resolve_period({'period': 'week', 'date': '2026-10-21'})  # a Wednesday
        self.assertEqual((start, end), (datetime.date(2026, 10, 18), datetime.date(2026, 10, 24)))
        kind, start, end, *_ = resolve_period({'period': 'month', 'month': '2026-02'})
        self.assertEqual((start, end), (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28)))

    def test_bad_input_falls_back_to_this_month(self):
        kind, start, end, *_ = resolve_period({'period': 'nonsense', 'month': 'zz'}, today=datetime.date(2026, 10, 21))
        self.assertEqual((kind, start, end), ('month', datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)))


class ReportContentTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional('rep')
        self.client.login(username='rep', password=PASSWORD)
        self.start, self.end = datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)
        self.new = make_patient(self.profile, 'New Man', gender='M', date_of_birth=datetime.date(1990, 1, 1), icd10_code='M54.5', diagnosis='Low back pain')
        self.old = make_patient(self.profile, 'Old Lady', gender='F', date_of_birth=datetime.date(1950, 1, 1), icd10_code='M54.5', diagnosis='Low back pain')
        Visit.objects.create(patient=self.old, date=datetime.date(2026, 9, 5), therapist='x')
        for patient, day in ((self.new, 3), (self.old, 4), (self.old, 11)):
            Visit.objects.create(patient=patient, date=datetime.date(2026, 10, day), therapist='x', progress='improving')
        self.report = build_report(self.profile, self.start, self.end)
        self.kpi = dict(self.report['kpis'])
        self.sections = {s['title']: s for s in self.report['sections']}

    def test_counts_are_right(self):
        self.assertEqual((self.kpi['Patients seen'], self.kpi['Visits / sessions'], self.kpi['New clients'], self.kpi['Follow-up clients']), (2, 3, 1, 1))

    def test_hmis_style_tables_split_new_from_followup_by_age_and_sex(self):
        new = {r[0]: r[1:] for r in self.sections['New clients by age and sex']['rows']}
        follow = {r[0]: r[1:] for r in self.sections['Follow-up clients by age and sex']['rows']}
        self.assertEqual(new['25-49'], [1, 0, 0, 1])   # male, 36 on 31 Oct
        self.assertEqual(follow['60+'], [0, 1, 0, 1])   # female, 76
        self.assertEqual(new['Total'], [1, 0, 0, 1])

    def test_diagnoses_and_period_boundaries(self):
        self.assertEqual(self.sections['Top diagnoses (patients seen)']['rows'][0], ['M54.5', 'Low back pain', 2, '100%'])
        empty = build_report(self.profile, datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
        self.assertEqual(dict(empty['kpis'])['Visits / sessions'], 0)

    def test_page_and_csv(self):
        page = self.client.get(reverse('accounts:reports'), {'period': 'month', 'month': '2026-10'})
        self.assertContains(page, 'October 2026')
        self.assertContains(page, 'New clients by age and sex')
        csv = self.client.get(reverse('accounts:reports'), {'period': 'month', 'month': '2026-10', 'export': 'csv'})
        self.assertEqual(csv['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('Follow-up clients by age and sex', csv.content.decode('utf-8'))
        weekly = self.client.get(reverse('accounts:reports'), {'period': 'week', 'date': '2026-10-04'})
        self.assertContains(weekly, 'Week of Oct 4')

    def test_reports_only_cover_my_own_patients_and_need_approval(self):
        other_user, other = make_professional('rep2')
        stranger = make_patient(other, 'Stranger')
        Visit.objects.create(patient=stranger, date=datetime.date(2026, 10, 2), therapist='y')
        self.assertEqual(dict(build_report(self.profile, self.start, self.end)['kpis'])['Visits / sessions'], 3)
        self.client.logout()
        make_professional('pending', status='submitted')
        self.client.login(username='pending', password=PASSWORD)
        self.assertRedirects(self.client.get(reverse('accounts:reports')), reverse('accounts:welcome'), fetch_redirect_response=False)
