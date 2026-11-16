import re

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from .helpers import PASSWORD, make_patient, make_professional

NO_CDN = ('cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'unpkg.com', 'stackpath.bootstrapcdn.com')


class SelfHostedAssetsTests(TestCase):
    def test_bundled_files_exist(self):
        for path in ('vendor/bootstrap/bootstrap.min.css', 'vendor/fontawesome/css/all.min.css', 'vendor/fontawesome/webfonts/fa-solid-900.woff2',
                     'accounts/auth.css', 'accounts/package.css', 'accounts/accounts.css', 'images/logo-64.png', 'images/logo-128.png', 'images/favicon.png', 'js/sajhya-ui.js'):
            self.assertIsNotNone(finders.find(path), path)

    def test_public_and_account_pages_do_not_depend_on_a_cdn(self):
        user, _ = make_professional()
        pages = [reverse('accounts:login'), reverse('accounts:package'), reverse('accounts:password-reset'), reverse('accounts:select-type', args=['professional'])]
        for url in pages:
            html = self.client.get(url).content.decode()
            for host in NO_CDN:
                self.assertNotIn(host, html, f'{url} still loads {host}')
        self.client.force_login(user)
        for url in (reverse('accounts:welcome'), reverse('accounts:password-change')):
            html = self.client.get(url).content.decode()
            self.assertFalse([h for h in NO_CDN if h in html], url)


class LoginPageTests(TestCase):
    def setUp(self):
        self.user, _ = make_professional()

    def test_page_has_the_expected_controls_as_buttons(self):
        html = self.client.get(reverse('accounts:login')).content.decode()
        self.assertEqual(html.count('class="btn-sj primary block"'), 1)  # Sign in
        for url, label in ((reverse('accounts:password-reset'), 'Forgot password?'), (reverse('accounts:package'), 'Get started'), (reverse('landing'), 'Home')):
            self.assertRegex(html, rf'<a href="{url}" class="btn-sj [a-z ]+">[^<]*<i[^>]*></i> {re.escape(label)}</a>')  # each is a styled button, not a plain link
        self.assertIn('data-pw-toggle', html)  # show / hide password
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('images/logo-128.png', html)

    def test_wrong_credentials_show_an_error_and_stay_on_the_page(self):
        r = self.client.post(reverse('accounts:login'), {'username': 'pro', 'password': 'wrong-password'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'auth-alert error')
        self.assertContains(r, 'value="pro"')  # the username is kept

    def test_next_is_respected_and_signed_in_users_skip_the_page(self):
        r = self.client.post(reverse('accounts:login'), {'username': 'pro', 'password': PASSWORD, 'next': reverse('accounts:patients')})
        self.assertRedirects(r, reverse('accounts:patients'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('accounts:login')), reverse('accounts:welcome'), fetch_redirect_response=False)

    def test_password_pages_share_the_layout(self):
        for url in (reverse('accounts:password-reset'), reverse('accounts:password-reset-done'), reverse('accounts:password-reset-complete')):
            html = self.client.get(url).content.decode()
            self.assertIn('auth-shell', html, url)
            self.assertIn('btn-sj', html, url)


class LogoTests(TestCase):
    def test_workspace_pages_show_the_sajhya_logo(self):
        user, profile = make_professional()
        patient = make_patient(profile)
        self.client.force_login(user)
        for url in (reverse('accounts:dashboard'), reverse('accounts:patients'), reverse('exercises:library'), reverse('accounts:patient-detail', args=[patient.pk])):
            html = self.client.get(url).content.decode()
            self.assertIn('images/logo-128.png', html, url)
            self.assertIn('images/favicon.png', html, url)

    def test_landing_uses_the_small_logo(self):
        for url in ('/',):
            html = self.client.get(url).content.decode()
            self.assertIn('images/logo-64.png', html, url)
            self.assertNotIn('img/logo.png', html, url)  # the 546 KB original is no longer loaded on every page
