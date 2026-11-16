from django.http import JsonResponse

from .models import LabTest, LabTestPanel


def lab_search(request):
    """Type-ahead used by the patient profile's lab-test section: tests and panels matching the text."""
    if not request.user.is_authenticated:
        return JsonResponse({'results': []}, status=401)
    from accounts.access import require_workspace
    require_workspace(request)  # clinical catalogue lookups belong to verified professionals
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    tests = LabTest.objects.filter(is_active=True, name__icontains=q)[:8]
    panels = LabTestPanel.objects.filter(is_active=True, name__icontains=q)[:4]
    return JsonResponse({'results': (
        [{'kind': 'test', 'id': t.pk, 'name': t.name, 'detail': t.get_category_display()} for t in tests]
        + [{'kind': 'panel', 'id': p.pk, 'name': p.name, 'detail': 'Panel'} for p in panels])})
