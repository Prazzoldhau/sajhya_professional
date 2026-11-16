import uuid
from decimal import Decimal

from django.db import models


class LabTest(models.Model):
    """A blood investigation people can book. The catalogue is managed in the admin so prices, wording and the
    list itself can change without a release. The starter prices came from the original project; review them
    before real use."""

    CATEGORY_CHOICES = [
        ('hematology', 'Hematology'), ('biochemistry', 'Biochemistry'), ('hormonal', 'Hormonal'),
        ('serology', 'Serology / Infection'), ('electrolytes', 'Electrolytes & Minerals'), ('urine', 'Urine'), ('other', 'Other'),
    ]

    name = models.CharField(max_length=150, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    sample_type = models.CharField(max_length=100, blank=True, help_text='e.g. "Blood - Venous"')
    prep_instructions = models.CharField(max_length=255, blank=True, help_text='e.g. "8-12 hours fasting required"')
    turnaround_time = models.CharField(max_length=100, blank=True, help_text='e.g. "Same day", "24 hours"')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name


class LabTestPanel(models.Model):
    """A bundle of tests sold together at one price, normally cheaper than buying each test alone."""

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    tests = models.ManyToManyField(LabTest, related_name='panels')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def a_la_carte_total(self):
        return sum((t.price for t in self.tests.all()), Decimal('0.00'))

    @property
    def savings(self):
        return self.a_la_carte_total - self.price
