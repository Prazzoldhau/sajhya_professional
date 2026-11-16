from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .access import first_error, workspace_context, workspace_profile

from .forms import SettingsEmailForm, SettingsPracticeForm, SettingsProfileForm

TABS = [('profile', 'My profile'), ('practice', 'Practice'), ('account', 'Account & security'), ('security', 'Two-step sign-in'), ('access', 'Access log')]


@login_required
def settings_page(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    tab = request.GET.get('tab') if request.GET.get('tab') in dict(TABS) else 'profile'
    if tab in ('security', 'access'):  # their own pages
        return redirect('accounts:security' if tab == 'security' else 'accounts:access-log')
    forms_by_tab = {
        'profile': lambda data=None, files=None: SettingsProfileForm(data, files, instance=profile),
        'practice': lambda data=None, files=None: SettingsPracticeForm(data, instance=profile),
        'account': lambda data=None, files=None: SettingsEmailForm(data, user=request.user),
    }
    if request.method == 'POST':
        tab = request.POST.get('tab') if request.POST.get('tab') in dict(TABS) else 'profile'
        form = forms_by_tab[tab](request.POST, request.FILES)
        if form.is_valid():
            if tab == 'account':
                request.user.email = form.cleaned_data['email']
                request.user.save(update_fields=['email'])
            else:
                form.save()
            messages.success(request, 'Settings saved.')
            return redirect(f'{request.path}?tab={tab}')
        messages.error(request, first_error(form))
    else:
        form = forms_by_tab[tab]()
    context = workspace_context(request.user, profile)
    context.update({'active': 'settings', 'tab': tab, 'tabs': TABS, 'form': form})
    return render(request, 'accounts/settings.html', context)
