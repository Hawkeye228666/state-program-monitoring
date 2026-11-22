import calendar
from datetime import date
from django.db import migrations

def backfill(apps,schema_editor):
    Period=apps.get_model('monitor','Period')
    for period in Period.objects.all().iterator():
        if '-Q' in period.code:
            q=int(period.code[-1]);period.kind='quarter'
            period.start=date(period.year,q*3-2,1);period.end=date(period.year,q*3,calendar.monthrange(period.year,q*3)[1])
        elif len(period.code)==4 and period.code.isdigit():
            period.kind='year';period.start=date(period.year,1,1);period.end=date(period.year,12,31)
        if not period.original:period.original=period.label
        period.save(update_fields=['kind','start','end','original'])

class Migration(migrations.Migration):
    dependencies=[('monitor','0005_observation_filter_indexes')]
    operations=[migrations.RunPython(backfill,migrations.RunPython.noop)]
