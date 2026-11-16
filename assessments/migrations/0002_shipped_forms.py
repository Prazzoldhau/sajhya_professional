from django.db import migrations


def add_shipped_forms(apps, schema_editor):
    from assessments import clinical_forms
    clinical_forms.sync(apps.get_model('assessments', 'ClinicalForm'))


class Migration(migrations.Migration):

    dependencies = [('assessments', '0001_initial')]

    operations = [migrations.RunPython(add_shipped_forms, migrations.RunPython.noop)]
