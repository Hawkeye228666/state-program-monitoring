from django.db import migrations,models

def guard_precision(apps,schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM monitor_observation WHERE numeric_text IS NOT NULL AND (numeric_text != round(numeric_text,30) OR abs(numeric_text) >= power(10::numeric,50))")
        if cursor.fetchone()[0]:raise ValueError('Existing values exceed NUMERIC(80,30); migration refused to prevent rounding. Back up and review precision.')

class Migration(migrations.Migration):
    dependencies=[('monitor','0002_exact_numeric')]
    operations=[migrations.RunPython(guard_precision,migrations.RunPython.noop),
        migrations.RenameField('observation','numeric_text','numeric_value'),
        migrations.AlterField('observation','numeric_value',models.DecimalField(max_digits=80,decimal_places=30,null=True,blank=True))]
