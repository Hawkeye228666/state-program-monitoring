from django.db import migrations
import monitor.fields
from django.conf import settings
from django.db import models
import django.db.models.deletion


def convert_numeric(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('ALTER TABLE monitor_observation ALTER COLUMN numeric_text TYPE numeric USING numeric_text::numeric')


def convert_text(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('ALTER TABLE monitor_observation ALTER COLUMN numeric_text TYPE text USING numeric_text::text')


def finite_constraint(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("ALTER TABLE monitor_observation ADD CONSTRAINT observation_finite_number CHECK (numeric_text IS NULL OR numeric_text NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric))")


def remove_constraint(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('ALTER TABLE monitor_observation DROP CONSTRAINT observation_finite_number')


class Migration(migrations.Migration):
    dependencies = [('monitor', '0001_initial'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="importrun", name="actor", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="import_runs", to=settings.AUTH_USER_MODEL)),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(convert_numeric, convert_text)],
            state_operations=[migrations.AlterField(model_name='observation', name='numeric_text', field=monitor.fields.ExactNumericTextField(blank=True, null=True))],
        ),
        migrations.RunPython(finite_constraint, remove_constraint),
    ]
