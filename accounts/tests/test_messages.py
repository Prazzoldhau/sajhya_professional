import datetime
from urllib.parse import unquote

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts import messaging
from accounts.models import MessageTemplate

from .helpers import PASSWORD, make_patient, make_professional


class RenderTests(TestCase):
    def test_placeholders_are_filled_and_empty_lines_dropped(self):
        body = 'Hello {patient},\nContact: {contact}\nBye {unknown}'
        self.assertEqual(messaging.render(body, {'patient': 'Sita', 'contact': ''}), 'Hello Sita,\nBye {unknown}')
        self.assertEqual(messaging.render('A {x}\n\n\n\nB', {'x': '1'}), 'A 1\n\nB')
        self.assertEqual(messaging.render('{patient.__class__}', {'patient': 'x'}), '{patient.__class__}')  # no attribute access, just names

    def test_whatsapp_number_cleaning(self):
        self.assertEqual(messaging.clean_whatsapp_number(' +977 970-2235789 '), '+977 970-2235789')
        self.assertEqual(messaging.clean_whatsapp_number(''), '')
        for bad in ('abc', '12345', '+977 <script>'):
            with self.assertRaises(ValueError):
                messaging.clean_whatsapp_number(bad)


class MessagesPageTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    def test_the_page_lists_every_message_and_the_business_number_can_be_set(self):
        page = self.client.get(reverse('accounts:messages'))
        self.assertEqual(page.status_code, 200)
        for label in ('Follow-up check-in', 'Home exercise programme message', 'SOAP note message', 'Business WhatsApp and Viber numbers'):
            self.assertContains(page, label)
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789'})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.whatsapp_number, '+977 970-2235789')
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': 'not a number'})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.whatsapp_number, '+977 970-2235789')  # a bad value is refused
        # the number is used in the messages the professional sends
        self.assertIn('WhatsApp +977 970-2235789', messaging.contact_text(self.profile))
        self.assertContains(self.client.get(reverse('accounts:messages')), 'wa.me/9779702235789')

    def test_a_message_can_be_reworded_and_reset_and_the_new_wording_is_used(self):
        self.client.post(reverse('accounts:message-save', args=['followup']), {'body': 'Namaste {patient}! How are you?'})
        self.assertEqual(messaging.render(messaging.body_for(self.profile, 'followup'), messaging.patient_values(self.profile, self.patient)), 'Namaste Sita Gurung! How are you?')
        self.assertContains(self.client.get(reverse('accounts:messages')), 'edited')
        self.client.post(reverse('accounts:message-save', args=['followup']), {'body': '   '})  # empty is refused, the old wording stays
        self.assertIn('Namaste', MessageTemplate.objects.get(key='followup').body)
        self.client.post(reverse('accounts:message-reset', args=['followup']))
        self.assertFalse(MessageTemplate.objects.exists())
        self.assertIn('It has been a while', messaging.body_for(self.profile, 'followup'))
        self.assertEqual(self.client.post(reverse('accounts:message-save', args=['made-up-key']), {'body': 'x'}).status_code, 302)
        self.assertFalse(MessageTemplate.objects.exists())  # only real messages can be saved

    def test_custom_notices_can_be_added_edited_deleted_and_are_private(self):
        self.client.post(reverse('accounts:custom-add'), {'title': 'Holiday closure', 'body': 'Hello {patient}, {practice} is closed on {date}.'})
        notice = MessageTemplate.objects.get(is_custom=True)
        self.assertTrue(notice.key.startswith('custom-'))
        self.client.post(reverse('accounts:message-save', args=[notice.key]), {'title': 'Holiday', 'body': 'Closed on {date}. Contact: {contact}'})
        notice.refresh_from_db()
        self.assertEqual((notice.title, notice.body), ('Holiday', 'Closed on {date}. Contact: {contact}'))
        self.client.post(reverse('accounts:custom-add'), {'title': '', 'body': 'no title'})
        self.assertEqual(MessageTemplate.objects.count(), 1)
        stranger, _ = make_professional('stranger')
        other = self.client_class()
        other.force_login(stranger)
        other.post(reverse('accounts:custom-delete', args=[notice.key]))
        other.post(reverse('accounts:message-save', args=[notice.key]), {'body': 'hijack'})
        notice.refresh_from_db()
        self.assertEqual(notice.body, 'Closed on {date}. Contact: {contact}')
        self.client.post(reverse('accounts:custom-delete', args=[notice.key]))
        self.assertFalse(MessageTemplate.objects.exists())

    def test_notice_page_prepares_a_message_for_each_patient_in_the_chosen_group(self):
        stale = make_patient(self.profile, 'Old Patient', phone='9841000555')
        stale.last_visit = timezone.localdate() - datetime.timedelta(days=40)
        stale.save()
        fresh = make_patient(self.profile, 'Fresh Patient')
        fresh.last_visit = timezone.localdate()
        fresh.save()
        page = self.client.get(reverse('accounts:notice-send'), {'t': 'followup', 'audience': 'followup'})
        names = [r['patient'].name for r in page.context['rows']]
        self.assertIn('Old Patient', names)
        self.assertNotIn('Fresh Patient', names)
        row = [r for r in page.context['rows'] if r['patient'].name == 'Old Patient'][0]
        self.assertTrue(row['url'].startswith('https://wa.me/9779841000555?text='))
        self.assertIn('Hello Old Patient', row['text'])
        self.assertContains(page, 'WhatsApp')
        self.client.post(reverse('accounts:custom-add'), {'title': 'Camp', 'body': 'Hi {patient}, free camp on {date} at {practice}.'})
        key = MessageTemplate.objects.get(is_custom=True).key
        page = self.client.get(reverse('accounts:notice-send'), {'t': key, 'audience': 'all', 'date': self.tomorrow.isoformat()})
        self.assertIn(f'free camp on {self.tomorrow:%d %b %Y}', page.context['rows'][0]['text'])
        found = self.client.get(reverse('accounts:notice-send'), {'audience': 'search', 'q': 'old'})
        self.assertEqual([r['patient'].name for r in found.context['rows']], ['Old Patient'])
        self.assertEqual(len(self.client.get(reverse('accounts:notice-send'), {'audience': 'search'}).context['rows']), 0)
        everyone = self.client.get(reverse('accounts:notice-send'), {'audience': 'all', 't': 'not-a-template'})
        self.assertEqual(everyone.status_code, 200)
        self.assertEqual(len(everyone.context['rows']), 3)

    def test_only_approved_workspaces_reach_the_messages_pages(self):
        make_professional('waiting', status='submitted')
        self.client.logout()
        self.client.login(username='waiting', password=PASSWORD)
        self.assertEqual(self.client.get(reverse('accounts:messages')).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('accounts:notice-send')).status_code, 302)


class ViberTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_professional()
        self.client.force_login(self.user)
        self.patient = make_patient(self.profile)
        self.tomorrow = timezone.localdate() + datetime.timedelta(days=1)

    def test_channel_links_put_the_patients_app_first_and_viber_copies_the_text(self):
        links = messaging.channel_links('9841234567', 'Hello there', 'viber')
        self.assertEqual([l['key'] for l in links], ['viber', 'whatsapp', 'sms'])
        viber = links[0]
        self.assertEqual((viber['url'], viber['copy'], viber['preferred']), ('viber://chat?number=%2B9779841234567', 'Hello there', True))
        self.assertTrue(links[1]['url'].startswith('https://wa.me/9779841234567?text='))
        self.assertTrue(links[2]['url'].startswith('sms:+9779841234567?body='))
        blank = messaging.channel_links('', 'Hello there', 'whatsapp')  # no number: the app's contact picker
        by_key = {l['key']: l for l in blank}
        self.assertTrue(by_key['viber']['url'].startswith('viber://forward?text='))
        self.assertEqual(by_key['viber']['copy'], '')
        self.assertEqual(by_key['sms']['url'], 'sms:?body=Hello%20there')
        self.assertEqual([l['key'] for l in messaging.channel_links('9841234567', 'x')], ['whatsapp', 'viber', 'sms'])

    def test_notices_offer_every_app_and_the_business_viber_number_appears_in_messages(self):
        self.patient.messaging_app = 'viber'
        self.patient.last_visit = timezone.localdate() - datetime.timedelta(days=40)
        self.patient.save()
        page = self.client.get(reverse('accounts:notice-send'), {'audience': 'followup'})
        row = page.context['rows'][0]
        self.assertEqual([l['key'] for l in row['links']], ['viber', 'whatsapp', 'sms'])
        self.assertContains(page, 'data-copy=')
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789', 'viber_number': '+977 980-1111111'})
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.whatsapp_number, self.profile.viber_number), ('+977 970-2235789', '+977 980-1111111'))
        self.assertIn('WhatsApp +977 970-2235789, Viber +977 980-1111111', messaging.contact_text(self.profile))
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789', 'viber_number': 'x'})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.viber_number, '+977 980-1111111')  # a bad number changes nothing

class WhatsAppWebTests(TestCase):
    def test_whatsapp_links_can_go_to_whatsapp_web(self):
        self.assertTrue(messaging.whatsapp_url('9841234567', 'Hi').startswith('https://wa.me/9779841234567?text='))
        self.assertTrue(messaging.whatsapp_url('9841234567', 'Hi', web=True).startswith('https://web.whatsapp.com/send?phone=9779841234567&text='))
        self.assertTrue(messaging.whatsapp_url('', 'Hi', web=True).startswith('https://web.whatsapp.com/send?text='))
        links = messaging.channel_links('9841234567', 'Hi', 'whatsapp', web=True)
        self.assertTrue(links[0]['url'].startswith('https://web.whatsapp.com/send?phone='))

    def test_the_setting_changes_every_whatsapp_button(self):
        user, profile = make_professional()
        self.client.force_login(user)
        patient = make_patient(profile)
        patient.last_visit = timezone.localdate() - datetime.timedelta(days=40)
        patient.save()
        first = self.client.get(reverse('accounts:notice-send'), {'audience': 'followup'}).context['rows'][0]['links'][0]['url']
        self.assertTrue(first.startswith('https://wa.me/'))
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789', 'whatsapp_web': 'on'})
        profile.refresh_from_db()
        self.assertTrue(profile.whatsapp_web)
        after = self.client.get(reverse('accounts:notice-send'), {'audience': 'followup'}).context['rows'][0]['links'][0]['url']
        self.assertTrue(after.startswith('https://web.whatsapp.com/send?phone=9779841000000'), after)
        self.assertContains(self.client.get(reverse('accounts:messages')), 'To send from a different WhatsApp number')
        self.client.post(reverse('accounts:whatsapp-number'), {'whatsapp_number': '+977 970-2235789'})  # unticked
        profile.refresh_from_db()
        self.assertFalse(profile.whatsapp_web)
