from django.db import migrations


def add_department_libraries(apps, schema_editor):
    from exercises import discipline_library
    discipline_library.sync(apps.get_model('exercises', 'Region'), apps.get_model('exercises', 'SubRegion'), apps.get_model('exercises', 'ExerciseMain'))


class Migration(migrations.Migration):

    dependencies = [('exercises', '0001_initial')]

    operations = [migrations.RunPython(add_department_libraries, migrations.RunPython.noop)]
