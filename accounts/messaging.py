"""The WhatsApp messages the workspace prepares for patients (follow-up, exercise programme, SOAP note, and
any notice the professional writes). Each message is a template with {placeholders}: the built-in wording can be changed per professional,
and custom notices can be added. Messages are opened in WhatsApp with wa.me links; the professional presses send."""
import re
from urllib.parse import quote

from django.utils import timezone

DEFAULTS = {
    'followup': {
        'label': 'Follow-up check-in',
        'help': 'For patients who have not visited for a while.',
        'body': 'Hello {patient},\nIt has been a while since your last visit to {practice}. How are you feeling?\nTo book your next session, contact us: {contact}',
    },
    'exercise_program': {
        'label': 'Home exercise programme message',
        'help': 'The text that goes with a home exercise programme (PDF with pictures, English and Nepali) sent to a patient by WhatsApp or e-mail.',
        'body': 'Hello {patient},\nYour home exercise programme from {practice} dated {date}: {link}\nThe link works for {days} days. Do the exercises as shown, and stop and contact us if you feel more pain.\nThank you.',
    },
    'soap_note': {
        'label': 'SOAP note message',
        'help': 'The text that goes with a finalised SOAP note sent to a patient by WhatsApp or e-mail.',
        'body': 'Hello {patient},\nYour physiotherapy note from {practice} dated {date}: {link}\nThe link works for {days} days.\nThank you.',
    },
}
BUILT_IN_ORDER = list(DEFAULTS)

PLACEHOLDERS = [
    ('patient', "The patient's name"), ('practice', 'Your practice (or clinic) name'), ('therapist', 'Your name'),
    ('day', 'Weekday, e.g. Tuesday'), ('date', 'Date, e.g. 27 Oct 2026'), ('time', 'Time, e.g. 3:00 PM'),
    ('contact', 'Your WhatsApp number and phone'), ('address', 'Your practice address'),
    ('invoice', 'Invoice number (bill message)'), ('amount', 'Bill amount (bill message)'),
]
SAMPLE = {
    'patient': 'Sita Gurung', 'practice': 'Your Practice', 'therapist': 'Your Name', 'day': 'Tuesday', 'date': '27 Oct 2026', 'time': '3:00 PM',
    'contact': 'WhatsApp +977 98xxxxxxx', 'address': 'Your address', 'invoice': 'BILL-1A2B3C4D', 'amount': '700', 'due_line': '', 'extra_line': '', 'link': 'https://...', 'days': '30', 'package': '10 Days package, 10 sessions',
}
_TOKEN = re.compile(r'\{(\w+)\}')


def render(body, values):
    """Fill {placeholders}. A line whose placeholders are all empty is dropped, so a missing phone number or an unused line never leaves
    a hole like "contact us: ". Unknown placeholders are left as typed."""
    out = []
    for line in (body or '').replace('\r\n', '\n').split('\n'):
        tokens = _TOKEN.findall(line)
        if tokens and all(t in values and not str(values[t]).strip() for t in tokens):
            continue
        out.append(_TOKEN.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), line))
    text = '\n'.join(out)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def body_for(profile, key):
    """The professional's own wording for this message, else the built-in one. A custom notice is looked up by its key."""
    from .models import MessageTemplate
    row = MessageTemplate.objects.filter(professional=profile, key=key).first()
    if row is not None:
        return row.body
    return DEFAULTS[key]['body'] if key in DEFAULTS else ''


def contact_text(profile):
    phone = profile.practice_phone or profile.mobile
    apps = []
    if profile.whatsapp_number:
        apps.append(f'WhatsApp {profile.whatsapp_number}')
    if profile.viber_number:
        apps.append(f'Viber {profile.viber_number}')
    if apps and phone and phone not in (profile.whatsapp_number, profile.viber_number):
        return ', '.join(apps) + f' or call {phone}'
    return ', '.join(apps) if apps else phone


def practice_values(profile):
    return {'practice': profile.practice_name or profile.full_name, 'therapist': profile.full_name, 'contact': contact_text(profile), 'address': profile.practice_address}


def fmt_time(dt):
    local = timezone.localtime(dt)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def patient_values(profile, patient, when=None):
    values = {**practice_values(profile), 'patient': patient.name, 'day': '', 'date': '', 'time': ''}
    if when is not None:
        values.update({'day': f'{when:%A}', 'date': f'{when:%d %b %Y}', 'time': fmt_time(when) if hasattr(when, 'hour') else ''})
    return values


def normalize_phone(raw):
    """Digits only with the country code, ready for wa.me. A local 10-digit number gets DEFAULT_COUNTRY_CODE; '' when unusable."""
    from django.conf import settings
    digits = re.sub(r'\D', '', raw or '')
    code = settings.DEFAULT_COUNTRY_CODE
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = code + digits[1:]
    elif len(digits) == 10:
        digits = code + digits
    return digits if 8 <= len(digits) <= 15 else ''


def whatsapp_chat(phone, web=False):
    """The bare WhatsApp chat with this number (no message), for sending a document as a file."""
    number = normalize_phone(phone)
    if web:
        return f'https://web.whatsapp.com/send?phone={number}' if number else 'https://web.whatsapp.com/'
    return f'https://wa.me/{number}' if number else 'https://web.whatsapp.com/'


def whatsapp_url(phone, text, web=False):
    """WhatsApp link with the message ready. It opens the patient's own chat when the number is usable, else WhatsApp's contact picker.
    With web=True it goes straight to WhatsApp Web (the browser), where whichever number is signed in there sends it."""
    number = normalize_phone(phone)
    if web:
        return f"https://web.whatsapp.com/send?phone={number}&text={quote(text)}" if number else f"https://web.whatsapp.com/send?text={quote(text)}"
    return f"https://wa.me/{number}?text={quote(text)}" if number else f"https://wa.me/?text={quote(text)}"


CHANNELS = [('whatsapp', 'WhatsApp'), ('viber', 'Viber'), ('sms', 'SMS')]


def channel_links(phone, text, preferred='whatsapp', web=False):
    """The ways to send this text to one patient, the patient's own app first. WhatsApp and SMS open the chat with the text ready. Viber
    cannot be given a text together with a chat, so its link opens the patient's chat (or the contact picker with no number) and the
    text is put on the clipboard for you to paste: the link carries a `copy` text that the page copies when it is clicked."""
    number = normalize_phone(phone)
    links = []
    for key, label in CHANNELS:
        copy = ''
        if key == 'whatsapp':
            url = whatsapp_url(phone, text, web)
        elif key == 'viber':
            url, copy = (f'viber://chat?number=%2B{number}', text) if number else (f'viber://forward?text={quote(text)}', '')
        else:
            url = f'sms:+{number}?body={quote(text)}' if number else f'sms:?body={quote(text)}'
        links.append({'key': key, 'label': label, 'url': url, 'copy': copy, 'preferred': key == preferred})
    links.sort(key=lambda link: not link['preferred'])  # the patient's own app first
    return links


def clean_whatsapp_number(value):
    """The business WhatsApp number as typed (spaces, dashes and a leading + are fine); at least 8 digits."""
    value = (value or '').strip()
    if not value:
        return ''
    if re.search(r'[^\d+\-\s()]', value) or len(re.sub(r'\D', '', value)) < 8:
        raise ValueError('Enter a WhatsApp number with the country code, for example +977 970-2235789.')
    return value[:20]


def email_ready():
    """False when the server only prints e-mails to its log (the console or dummy backend), so nothing really leaves it. Pages that send e-mail check this
    first, rather than saying "sent" for a message nobody will receive."""
    from django.conf import settings
    backend = settings.EMAIL_BACKEND.lower()
    return not ('console' in backend or 'dummy' in backend)


EMAIL_NOT_SET_UP = 'E-mail is not set up on this server yet, so nothing was sent. Ask the administrator to set up e-mail sending, or use the PDF download or WhatsApp instead.'
