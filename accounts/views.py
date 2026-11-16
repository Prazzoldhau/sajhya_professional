import datetime
import mimetypes

from django.contrib.auth import login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from sajhya_health.throttle import too_many

from .access import actor_of, can_see_contact, first_error, own_patient, own_profile, staff_required, workspace_context, workspace_profile
from .services import record_visit
from .forms import SUBTYPES, STEP_FORMS, STEP_TITLES, PatientEditForm, PatientForm, PatientNotesForm, PatientPhotoForm, ProfilePictureForm, SignupForm, VisitForm
from assessments import disciplines
from . import audit
from .treatments import parse_treatments, ui_for
from .models import Account, Icd10Code, Patient, ProfessionalProfile, Visit


def package(request):
    return redirect('accounts:select-type', account_type='professional')


def select_type(request, account_type):
    if account_type not in SUBTYPES:
        return redirect('landing')
    model, _, label = SUBTYPES[account_type]
    return render(request, 'accounts/select_type.html', {'account_type': account_type, 'label': label, 'options': model.objects.all()})


def signup(request, account_type, subtype_id):
    if account_type not in SUBTYPES:
        return redirect('landing')
    subtype = get_object_or_404(SUBTYPES[account_type][0], pk=subtype_id)
    if request.method == 'POST' and too_many(request, 'signup', 10):
        messages.error(request, 'Too many accounts were created from this connection in the last hour. Please try again later.')
        return redirect(request.path)
    form = SignupForm(request.POST or None, request.FILES or None, subtype=subtype)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return redirect('accounts:professional-step', step=2)
    return render(request, 'accounts/signup.html', {'form': form, 'account_type': account_type, 'subtype': subtype})


@login_required
def welcome(request):
    """Landing page after sign-in. Approved professionals go straight to the dashboard; everyone else sees where they are
    (unfinished onboarding, under review, or rejected with the reason)."""
    profile = getattr(getattr(request.user, 'account', None), 'profile', None)
    if profile and profile.status == ProfessionalProfile.APPROVED:
        return redirect('accounts:dashboard')
    next_step = None
    if profile and profile.status == ProfessionalProfile.DRAFT:
        next_step = min(profile.completed_step + 1, 5)
    elif profile and profile.status == ProfessionalProfile.REJECTED:
        next_step = 2
    return render(request, 'accounts/welcome.html', {'profile': profile, 'next_step': next_step})


@login_required
def professional_step(request, step):
    profile = own_profile(request)
    if profile.status not in (ProfessionalProfile.DRAFT, ProfessionalProfile.REJECTED):
        return redirect('accounts:welcome')
    forms_for, titles = STEP_FORMS, STEP_TITLES
    if step not in forms_for and step != 5:
        raise Http404
    if step > profile.completed_step + 1:  # no skipping ahead
        return redirect('accounts:professional-step', step=profile.completed_step + 1)

    context = {'profile': profile, 'step': step, 'titles': titles,
               'steps': [(n, label, n <= profile.completed_step) for n, label in titles.items()]}

    if step == 5:
        if request.method == 'POST':
            if profile.completed_step < 4:
                return redirect('accounts:professional-step', step=profile.completed_step + 1)
            profile.status = ProfessionalProfile.SUBMITTED
            profile.submitted_at = timezone.now()
            profile.rejection_reason = ''
            profile.save(update_fields=['status', 'submitted_at', 'rejection_reason'])
            return redirect('accounts:welcome')
        return render(request, 'accounts/professional_review.html', context)

    save_for_later = request.POST.get('action') == 'later'
    form = forms_for[step](request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST':
        if save_for_later:
            for field in form.fields.values():  # partial progress is allowed
                field.required = False
        if form.is_valid():
            form.save()
            if save_for_later:
                return redirect('accounts:welcome')
            if step > profile.completed_step:
                profile.completed_step = step
                profile.save(update_fields=['completed_step'])
            return redirect('accounts:professional-step', step=step + 1)
    context['form'] = form
    return render(request, 'accounts/professional_step.html', context)


@login_required
def professional_document(request, field, profile_id=None):
    """Credential files are private: only the owner or staff can open them."""
    if field not in ProfessionalProfile.DOCUMENT_FIELDS:
        raise Http404
    if profile_id is not None and request.user.is_staff:
        profile = get_object_or_404(ProfessionalProfile, pk=profile_id)
    else:
        profile = own_profile(request)
    document = getattr(profile, field)
    if not document:
        raise Http404
    if request.user.is_staff:
        audit.log_access(request, 'operator', workspace=profile, detail=f'opened the credential file {field}', operator=True)
    content_type = mimetypes.guess_type(document.name)[0] or 'application/octet-stream'
    return FileResponse(document.open('rb'), content_type=content_type)




@staff_required
def review_list(request):
    status = request.GET.get('status', ProfessionalProfile.SUBMITTED)
    profiles = ProfessionalProfile.objects.select_related('account__user', 'account__profession')
    if status != 'all':
        profiles = profiles.filter(status=status)
    return render(request, 'accounts/review_list.html', {
        'profiles': profiles.order_by('submitted_at', 'created_at'),
        'status': status,
        'status_choices': ProfessionalProfile.STATUS_CHOICES,
    })


@staff_required
def review_detail(request, profile_id):
    profile = get_object_or_404(ProfessionalProfile, pk=profile_id)
    if request.method == 'POST':
        decision = request.POST.get('decision')
        reason = request.POST.get('reason', '').strip()
        if decision == 'approve':
            profile.status = ProfessionalProfile.APPROVED
            profile.rejection_reason = ''
        elif decision == 'reject' and reason:
            profile.status = ProfessionalProfile.REJECTED
            profile.rejection_reason = reason
        else:
            messages.error(request, 'Give a reason when rejecting an application.')
            return redirect('accounts:review-detail', profile_id=profile.pk)
        profile.reviewed_at = timezone.now()
        profile.reviewed_by = request.user
        profile.save()
        messages.success(request, f'{profile.full_name}: {profile.get_status_display()}')
        return redirect('accounts:review-list')
    return render(request, 'accounts/review_detail.html', {'profile': profile})


@login_required
def dashboard(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    context = workspace_context(request.user, profile)
    context.update(_dashboard_data(profile))
    context['active'] = 'dashboard'
    return render(request, 'accounts/dashboard.html', context)


def followups_due(patients, today):
    """Active patients not seen for 14 days (or never): the dashboard's Follow-ups Due card and the patient-list filter share this."""
    stale = today - datetime.timedelta(days=14)
    return patients.filter(status=Patient.ACTIVE).filter(Q(last_visit__isnull=True) | Q(last_visit__lte=stale))


def treated_on(profile, day):
    """Sessions on one day for this workspace's patients, oldest first, each with who treated and when it was recorded, plus the day's counts."""
    visits = list(Visit.objects.filter(patient__in=profile.workspace_patients(), date=day).select_related('patient').prefetch_related('treatments').order_by('created_at', 'id'))
    for v in visits:
        v.recorded_time = timezone.localtime(v.created_at)
        v.given = [t for t in v.treatments.all() if t.kind == 'clinical']
        v.exercises = [t for t in v.treatments.all() if t.kind == 'exercise']
    summary = {'sessions': len(visits), 'patients': len({v.patient_id for v in visits}), 'by_therapist': sum(1 for v in visits if not v.is_by_assistant),
               'by_assistant': sum(1 for v in visits if v.is_by_assistant)}
    return visits, summary


def _dashboard_data(profile):
    today = timezone.localdate()
    patients = profile.workspace_patients()
    needs_followup = followups_due(patients, today)
    treated_visits, treated_summary = treated_on(profile, today)

    visits = Visit.objects.filter(patient__in=patients)
    window_start = today - datetime.timedelta(days=6)
    prev_start = window_start - datetime.timedelta(days=7)
    visits_week = visits.filter(date__gte=window_start, date__lte=today).count()
    visits_prev = visits.filter(date__gte=prev_start, date__lt=window_start).count()
    per_day = {d: 0 for d in (window_start + datetime.timedelta(days=i) for i in range(7))}
    for d in visits.filter(date__gte=window_start, date__lte=today).values_list('date', flat=True):
        per_day[d] += 1
    peak = max(per_day.values()) or 1
    chart = [{'label': d.strftime('%a'), 'count': n, 'height': max(round(n / peak * 100), 4)} for d, n in per_day.items()]

    change = visits_week - visits_prev
    return {
        'today': today,
        'stats': {
            'total': patients.count(),
            'active': patients.filter(status=Patient.ACTIVE).count(),
            'followups_due': needs_followup.count(),
            'visits_week': visits_week, 'visits_change': change, 'visits_change_abs': abs(change),
            'treated_today': treated_summary['patients'],
        },
        'treated': treated_visits[-8:][::-1], 'treated_summary': treated_summary,
        'recent': profile.recent_patients(4),
        'reminders': needs_followup.order_by(F('last_visit').asc(nulls_first=True))[:3],
        'chart': chart,
    }


@login_required
def profile_picture(request):
    profile = own_profile(request)
    form = ProfilePictureForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile photo updated.')
        return redirect('accounts:welcome')
    return render(request, 'accounts/profile_picture.html', {'form': form, 'profile': profile})


AGE_BUCKETS = {'child': (0, 17), 'adult': (18, 40), 'middle': (41, 60), 'senior': (61, 150)}
SORTS = {'recent': '-created_at', 'name': 'name', 'visit': '-last_visit'}


@login_required
def patient_list(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    all_patients = profile.workspace_patients()
    patients = all_patients

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    followup = request.GET.get('followup') == 'due'
    age = request.GET.get('age', '')
    sort = request.GET.get('sort', 'recent')
    if q:
        patients = patients.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(patient_code__icontains=q))
    if status in dict(Patient.STATUS_CHOICES):
        patients = patients.filter(status=status)
    if followup:
        patients = followups_due(patients, timezone.localdate())
    if age in AGE_BUCKETS:
        low, high = AGE_BUCKETS[age]
        today = timezone.localdate()
        # age between low and high  <=>  born after (today - high - 1y) and on/before (today - low y)
        oldest = today.replace(year=today.year - high - 1) if today.month != 2 or today.day != 29 else today.replace(year=today.year - high - 1, day=28)
        youngest = today.replace(year=today.year - low) if today.month != 2 or today.day != 29 else today.replace(year=today.year - low, day=28)
        patients = patients.filter(date_of_birth__gt=oldest, date_of_birth__lte=youngest)
    patients = patients.order_by(SORTS.get(sort, SORTS['recent']), '-id')

    page_obj = Paginator(patients, 10).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    counts = all_patients.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status=Patient.ACTIVE)),
        on_hold=Count('id', filter=Q(status=Patient.ON_HOLD)),
        discharged=Count('id', filter=Q(status=Patient.DISCHARGED)),
    )
    recent = list(profile.recent_patients(5))
    hidden = {p.pk for p in list(page_obj) + recent if not can_see_contact(profile, p)}
    context = workspace_context(request.user, profile)
    context.update({
        'hidden_contact': hidden, 'active': 'patients', 'page_obj': page_obj, 'counts': counts, 'q': q, 'status': status, 'followup': followup,
        'age': age, 'sort': sort, 'querystring': params.urlencode(),
        'recent_patients': recent,
        'status_choices': Patient.STATUS_CHOICES,
        'form': PatientForm(),
    })
    return render(request, 'accounts/patients.html', context)


@login_required
def patient_add(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    form = PatientForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        patient = form.save(commit=False)
        patient.professional = profile
        patient.registered_by_name, patient.registered_by_role = actor_of(request.user, profile)
        patient.save()
        messages.success(request, f'{patient.name} added ({patient.patient_code}).')
        return redirect('accounts:patients')
    context = workspace_context(request.user, profile)
    context.update({'active': 'patients', 'form': form})
    return render(request, 'accounts/patient_add.html', context)


@login_required
def patient_detail(request, pk):
    profile, patient = own_patient(request, pk)
    patient.touch()  # opening a patient puts them at the top of "Recent patients"
    tab = request.GET.get('tab', 'overview')
    if tab not in ('overview', 'plan', 'exercises', 'visits', 'profile', 'assessments', 'soap', 'notes', 'documents'):
        tab = 'overview'
    audit.log_access(request, 'view', patient=patient, detail=f'opened the {tab} tab')
    context = workspace_context(request.user, profile)
    context.update({
        'active': 'patients', 'patient': patient, 'tab': tab, 'show_contact': can_see_contact(profile, patient),
        'session_count': patient.visits.count(),
        'recent_visits': patient.visits.prefetch_related('treatments')[:3],
        'visits': patient.visits.prefetch_related('treatments') if tab == 'visits' else None,
        'plans': patient.plans.prefetch_related('phases') if tab == 'plan' else None,
        'prescriptions': patient.prescriptions.prefetch_related('exercises__exercise__step_images', 'exercises__feedback_logs') if tab == 'exercises' else None,
        'visit_form': VisitForm(initial={'date': timezone.localdate()}),
        'treat_ui': ui_for(disciplines.allowed(profile)),
        'notes_form': PatientNotesForm(instance=patient),
    })
    if tab == 'soap':
        context['soap_notes'] = patient.soap_notes.all()
    if tab == 'assessments':
        from assessments.services import patient_summary
        context['summary'] = patient_summary(patient, disciplines.visible_filter(disciplines.allowed(profile)))
        context['disciplines'] = disciplines.LABELS
        context['show_discipline'] = len(disciplines.allowed(profile)) > 1
    if tab == 'profile':
        from profiles.views import profile_context
        context.update(profile_context(patient, request.GET.get('section'), request.GET.get('therapy', 'physio')))
    return render(request, 'accounts/patient_detail.html', context)


@login_required
def patient_edit(request, pk):
    profile, patient = own_patient(request, pk)
    form = PatientEditForm(request.POST or None, request.FILES or None, instance=patient)
    show_contact = can_see_contact(profile, patient)
    if not show_contact:
        for name in ('phone', 'messaging_app', 'email', 'address'):
            del form.fields[name]  # a clinic physio can neither read nor overwrite the patient's contact details
    if request.method == 'POST' and form.is_valid():
        form.save()  # (also removes a replaced picture)
        messages.success(request, 'Patient updated.')
        return redirect('accounts:patient-detail', pk=patient.pk)
    context = workspace_context(request.user, profile)
    context.update({'active': 'patients', 'patient': patient, 'form': form, 'show_contact': show_contact})
    return render(request, 'accounts/patient_edit.html', context)


@login_required
def patient_visit_add(request, pk):
    profile, patient = own_patient(request, pk)
    if request.method == 'POST':
        form = VisitForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            given = parse_treatments(request.POST.get('treatments'))
            record_visit(patient, profile.full_name, data['date'], data['session_type'], data['progress'], data['notes'], given, professional=profile)
            messages.success(request, 'Session recorded' + (f' with {len(given)} treatment{"s" if len(given) != 1 else ""}.' if given else '.'))
        else:
            messages.error(request, 'Could not save the session - check the date and session type.')
    return redirect('accounts:patient-detail', pk=patient.pk)


@login_required
def patient_notes(request, pk):
    profile, patient = own_patient(request, pk)
    if request.method == 'POST':
        form = PatientNotesForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, 'Notes saved.')
    return redirect(f"{reverse('accounts:patient-detail', args=[patient.pk])}?tab=notes")


@login_required
def patient_search(request):
    """Type-ahead that picks one of the professional's patients (the exercise library uses it): match name, phone or patient ID."""
    profile = workspace_profile(request)
    if profile is None:
        return JsonResponse({'results': []})
    q = request.GET.get('q', '').strip()
    patients = profile.workspace_patients().exclude(status='discharged')
    if q:
        patients = patients.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(patient_code__icontains=q))
    return JsonResponse({'results': [
        {'id': p.pk, 'name': p.name, 'code': p.patient_code, 'phone': p.phone, 'age': p.age, 'gender': p.gender}
        for p in patients.order_by('name')[:10]]})


@login_required
def icd10_search(request):
    """Autocomplete for the diagnosis fields: match a code prefix or any word of the title."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    codes = Icd10Code.objects.filter(code__istartswith=q.replace(' ', ''))[:15]
    results = list(codes)
    if len(results) < 15:
        taken = {c.code for c in results}
        title_q = Q()
        for word in q.split():
            title_q &= Q(title__icontains=word)
        results += [c for c in Icd10Code.objects.filter(title_q)[:30] if c.code not in taken][:15 - len(results)]
    return JsonResponse({'results': [{'code': c.code, 'title': c.title} for c in results]})


@login_required
def patient_photo(request, pk, version=None):
    """Patient pictures are private: only the owning professional can load them."""
    profile, patient = own_patient(request, pk)
    if not patient.photo:
        raise Http404
    response = FileResponse(patient.photo.open('rb'), content_type='image/jpeg')
    response['Cache-Control'] = 'private, max-age=86400'  # the file name in the URL changes whenever the picture does
    return response


@login_required
def patient_photo_update(request, pk):
    profile, patient = own_patient(request, pk)
    if request.method == 'POST':
        form = PatientPhotoForm(request.POST, request.FILES, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile picture removed.' if form.cleaned_data.get('remove') else 'Profile picture updated.')
        else:
            messages.error(request, first_error(form))
    return redirect('accounts:patient-detail', pk=patient.pk)


@login_required
def treated_page(request):
    """Who was treated on a day, by whom and when: every session recorded for the workspace's patients."""
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    today = timezone.localdate()
    try:
        day = datetime.date.fromisoformat(request.GET.get('date', ''))
    except ValueError:
        day = today
    visits, summary = treated_on(profile, day)
    context = workspace_context(request.user, profile)
    context.update({'active': 'dashboard', 'day': day, 'today': today, 'visits': visits, 'summary': summary,
                    'prev_day': day - datetime.timedelta(days=1), 'next_day': day + datetime.timedelta(days=1)})
    return render(request, 'accounts/treated.html', context)
