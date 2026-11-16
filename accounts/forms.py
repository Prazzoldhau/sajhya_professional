import os

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from .images import normalize_photo
from .widgets import date_widget, datetime_widget, time_widget
from .models import Account, Patient, ProfessionalProfile, Profession, Visit

User = get_user_model()

SUBTYPES = {Account.PROFESSIONAL: (Profession, 'profession', 'Profession')}  # account type -> (subtype model, Account field, label)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}


SIGNATURES = {'.pdf': (b'%PDF-',), '.png': (b'\x89PNG\r\n\x1a\n',), '.jpg': (b'\xff\xd8\xff',), '.jpeg': (b'\xff\xd8\xff',)}


def validate_document(f):
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError('Upload a PDF, JPEG or PNG file.')
    if f.size > MAX_UPLOAD_BYTES:
        raise ValidationError('File is larger than 5 MB.')
    head = f.read(16)
    f.seek(0)
    if not head.startswith(SIGNATURES[ext]):  # the content must match the extension, not just the name
        raise ValidationError('This file does not look like a valid ' + ext.lstrip('.').upper() + '.')


def validate_image(f):
    if os.path.splitext(f.name)[1].lower() not in {'.jpg', '.jpeg', '.png'}:
        raise ValidationError('Upload a JPEG or PNG image.')
    if f.size > MAX_UPLOAD_BYTES:
        raise ValidationError('Image is larger than 5 MB.')


class ProfilePictureForm(forms.ModelForm):
    class Meta:
        model = ProfessionalProfile
        fields = ('profile_picture',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profile_picture'].validators.append(validate_image)
        self.fields['profile_picture'].widget.attrs['accept'] = '.jpg,.jpeg,.png'


class SignupForm(UserCreationForm):
    email = forms.EmailField()
    first_name = forms.CharField(max_length=100, label='First name (as on your licence)')
    middle_name = forms.CharField(max_length=100, required=False)
    last_name = forms.CharField(max_length=100)
    mobile = forms.CharField(max_length=20, label='Mobile phone')
    title = forms.CharField(max_length=30, label='Professional title', help_text='e.g. PT, DPT, MSPT')
    profile_picture = forms.ImageField(required=False, validators=[validate_image], help_text='Optional -- JPEG or PNG, up to 5 MB.')

    PROFESSIONAL_FIELDS = ('first_name', 'middle_name', 'last_name', 'mobile', 'title', 'profile_picture')

    class Meta:
        model = User
        fields = ('username', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('This e-mail address cannot be used to create an account. If you already registered, sign in, or use "Forgot your password?".')
        return email

    def __init__(self, *args, subtype, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtype = subtype
        self.order_fields(['first_name', 'middle_name', 'last_name', 'title', 'email', 'mobile', 'profile_picture', 'username', 'password1', 'password2'])

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.save()
        account = Account.objects.create(user=user, account_type=Account.PROFESSIONAL, profession=self.subtype)
        fields = {f: self.cleaned_data[f] for f in self.PROFESSIONAL_FIELDS if self.cleaned_data.get(f)}
        ProfessionalProfile.objects.create(account=account, **fields)
        return user


class CredentialsForm(forms.ModelForm):
    class Meta:
        model = ProfessionalProfile
        fields = ('license_number', 'issuing_authority', 'license_expiry')
        widgets = {'license_expiry': date_widget()}
        labels = {'license_number': 'Licence / registration number',
                  'issuing_authority': 'Issuing authority / board',
                  'license_expiry': 'Licence expiry date'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('license_number', 'issuing_authority', 'license_expiry'):
            self.fields[name].required = True


class DocumentsForm(forms.ModelForm):
    class Meta:
        model = ProfessionalProfile
        fields = ('id_document', 'license_document', 'degree_document')
        labels = {
            'id_document': 'Government-issued ID (passport, driving licence or national ID)',
            'license_document': 'Proof of professional licence',
            'degree_document': 'Academic degrees / certifications (e.g. BPT, DPT, specialisations)',
        }
        help_texts = {'id_document': 'PDF, JPEG or PNG, up to 5 MB each.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self._meta.fields:
            f = self.fields[name]
            f.validators.append(validate_document)
            f.widget.attrs['accept'] = '.pdf,.jpg,.jpeg,.png'
            f.required = not getattr(self.instance, name)  # already uploaded -> keep it


class PracticeForm(forms.ModelForm):
    class Meta:
        model = ProfessionalProfile
        fields = ('years_experience', 'focus_areas', 'services')
        widgets = {'focus_areas': forms.CheckboxSelectMultiple, 'services': forms.CheckboxSelectMultiple}
        labels = {'focus_areas': 'Areas of clinical focus', 'services': 'Services offered'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['years_experience'].required = True
        self.fields['years_experience'].widget.attrs['min'] = 0
        self.fields['focus_areas'].required = True
        self.fields['services'].required = True


class SettingsProfileForm(forms.ModelForm):
    """What a professional may change themselves. Name, title and licence details are deliberately absent: they were
    verified by staff, so changing them would sidestep verification."""
    class Meta:
        model = ProfessionalProfile
        fields = ('profile_picture', 'mobile', 'years_experience', 'focus_areas', 'services')
        widgets = {'focus_areas': forms.CheckboxSelectMultiple, 'services': forms.CheckboxSelectMultiple}
        labels = {'focus_areas': 'Areas of clinical focus', 'services': 'Services offered'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profile_picture'].validators.append(validate_image)
        self.fields['profile_picture'].widget = forms.FileInput(attrs={'accept': '.jpg,.jpeg,.png'})
        self.fields['mobile'].required = True


class SettingsPracticeForm(forms.ModelForm):
    class Meta:
        model = ProfessionalProfile
        fields = ('practice_name', 'practice_address', 'practice_phone', 'facility_code')
        labels = {'practice_name': 'Clinic / practice name', 'practice_address': 'Address', 'practice_phone': 'Practice phone'}


class SettingsEmailForm(forms.Form):
    email = forms.EmailField(label='Email address (used to sign in help and password reset)')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['email'].initial = user.email

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError('Another account already uses this email address.')
        return email


STEP_FORMS = {2: CredentialsForm, 3: DocumentsForm, 4: PracticeForm}
STEP_TITLES = {1: 'Account', 2: 'Credentials', 3: 'Documents', 4: 'Practice', 5: 'Review'}


class AgeOrBirthDate(forms.Form):
    """The date of birth and the age are both optional. Many patients do not know their date of birth: an age in years is accepted
    instead, and the date of birth is then an estimate. A real date of birth always wins over an age typed beside it."""
    age = forms.IntegerField(required=False, min_value=0, max_value=120, label='Age (years)',
                             widget=forms.NumberInput(attrs={'placeholder': 'If the date of birth is not known', 'min': 0, 'max': 120}))

    def clean(self):
        data = super().clean()
        born, age = data.get('date_of_birth'), data.get('age')
        if born:
            self.instance.dob_is_estimate = False
        elif age is not None:
            today = timezone.localdate()
            try:
                data['date_of_birth'] = today.replace(year=today.year - age)
            except ValueError:  # 29 February
                data['date_of_birth'] = today.replace(year=today.year - age, day=28)
            self.instance.dob_is_estimate = True
        else:  # neither is known: that is allowed, the age simply stays blank
            self.instance.dob_is_estimate = False
        return data


class PatientForm(AgeOrBirthDate, forms.ModelForm):
    class Meta:
        model = Patient
        fields = ('photo', 'name', 'date_of_birth', 'gender', 'phone', 'messaging_app', 'email', 'address',
                  'occupation', 'referral_source', 'diagnosis', 'icd10_code', 'notes')
        widgets = {
            'date_of_birth': date_widget(),
            'photo': forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
            'name': forms.TextInput(attrs={'placeholder': 'Enter full name'}),
            'phone': forms.TextInput(attrs={'placeholder': 'Enter phone number'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Optional'}),
            'address': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Enter address'}),
            'occupation': forms.TextInput(attrs={'placeholder': 'Enter occupation'}),
            'diagnosis': forms.TextInput(attrs={'placeholder': 'e.g. Chronic Low Back Pain'}),
            'icd10_code': forms.TextInput(attrs={'placeholder': 'e.g. M54.5'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Any additional notes...'}),
        }
        labels = {'name': 'Full Name', 'date_of_birth': 'Date of Birth', 'phone': 'Phone Number', 'photo': 'Profile picture'}

    def clean_date_of_birth(self):
        born = self.cleaned_data.get('date_of_birth')
        today = timezone.localdate()
        if born and born > today:
            raise ValidationError('The date of birth cannot be in the future.')
        if born and born.year < today.year - 120:
            raise ValidationError('Check the date of birth: that would make the patient over 120 years old.')
        return born

    def clean_messaging_app(self):
        return self.cleaned_data.get('messaging_app') or self.instance.messaging_app or 'whatsapp'

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if isinstance(photo, UploadedFile):  # a fresh upload (not the file already stored)
            return normalize_photo(photo, 'patient')  # validated, resized, metadata stripped
        return photo

    def save(self, commit=True):
        old = self._old_photo
        patient = super().save(commit=commit)
        if commit and old and old != (patient.photo.name if patient.photo else ''):
            patient._meta.get_field('photo').storage.delete(old)  # editing the picture must not leave the old file behind
        return patient

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_photo = self.instance.photo.name if self.instance.pk and self.instance.photo else ''
        self.fields['messaging_app'].required = False
        for name in ('name', 'gender', 'phone'):
            self.fields[name].required = True
        if self.instance.pk and self.instance.dob_is_estimate and self.instance.age is not None:
            self.fields['age'].initial = self.instance.age
        self.fields['gender'].choices = [('', 'Select gender')] + Patient.GENDER_CHOICES
        self.fields['referral_source'].choices = [('', 'Select option')] + Patient.REFERRAL_CHOICES


class PatientEditForm(PatientForm):
    class Meta(PatientForm.Meta):
        fields = PatientForm.Meta.fields + ('status', 'insurance')


class VisitForm(forms.ModelForm):
    class Meta:
        model = Visit
        fields = ('date', 'session_type', 'progress', 'notes')
        widgets = {'date': date_widget(),
                   'notes': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Session notes (optional)'})}


class PatientNotesForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ('notes',)
        widgets = {'notes': forms.Textarea(attrs={'rows': 8, 'placeholder': 'Clinical notes about this patient...'})}


class PatientPhotoForm(forms.ModelForm):
    """Change or remove the picture from the patient page."""
    remove = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_photo = self.instance.photo.name if self.instance.photo else ''  # validation overwrites instance.photo

    class Meta:
        model = Patient
        fields = ('photo',)
        widgets = {'photo': forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'})}

    def clean(self):
        data = super().clean()
        if not data.get('remove') and not data.get('photo'):
            raise ValidationError('Choose a picture to upload.')
        return data

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if isinstance(photo, UploadedFile):
            return normalize_photo(photo, 'patient')
        return photo

    def save(self, commit=True):
        patient = self.instance
        old = self._old_photo
        if self.cleaned_data.get('remove'):
            patient.photo = ''
        elif self.cleaned_data.get('photo'):
            patient.photo = self.cleaned_data['photo']
        patient.save(update_fields=['photo'])
        if old and old != (patient.photo.name if patient.photo else ''):  # do not leave the replaced file behind
            patient._meta.get_field('photo').storage.delete(old)
        return patient


class StyledAuthenticationForm(AuthenticationForm):
    """Sign-in form with the placeholders / autocomplete hints the sign-in page expects."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'autofocus': True, 'autocomplete': 'username', 'placeholder': 'Your username', 'autocapitalize': 'none'})
        self.fields['password'].widget.attrs.update({'autocomplete': 'current-password', 'placeholder': 'Your password'})


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].widget.attrs.update({'autofocus': True, 'autocomplete': 'email', 'placeholder': 'you@example.com'})


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].widget.attrs.update({'autofocus': True, 'placeholder': 'New password'})
        self.fields['new_password2'].widget.attrs.update({'placeholder': 'Type it again'})
