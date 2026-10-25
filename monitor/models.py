import json
from decimal import Decimal
from django.db import models

class Program(models.Model):
    slug = models.SlugField(unique=True)
    name = models.TextField()
    summary = models.TextField()
    schedule = models.TextField()
    sources = models.JSONField(default=list)
    def __str__(self): return self.name

class Indicator(models.Model):
    program = models.ForeignKey(Program,on_delete=models.PROTECT,related_name='indicators')
    file_id = models.CharField(max_length=80,unique=True)
    metadata_id = models.CharField(max_length=80)
    name = models.TextField()
    unit = models.TextField(blank=True)
    methodology = models.TextField(blank=True)
    organization = models.TextField(blank=True)
    forms = models.JSONField(default=list)
    metadata = models.JSONField(default=dict)
    def __str__(self): return self.name

class Territory(models.Model):
    code = models.CharField(max_length=80,unique=True)
    name = models.TextField()
    kind = models.CharField(max_length=20,choices=[('country','Российская Федерация'),('district','Федеральный округ'),('subject','Субъект РФ'),('municipality','Город / муниципалитет'),('aggregate','Специальный агрегат'),('unknown','Не определён')],db_index=True)
    def __str__(self): return self.name

class Period(models.Model):
    code = models.CharField(max_length=80,unique=True)
    label = models.CharField(max_length=160)
    year = models.IntegerField()
    order = models.CharField(max_length=100,db_index=True)
    class Meta: ordering=['order']

class Dimension(models.Model):
    indicator = models.ForeignKey(Indicator,on_delete=models.CASCADE,related_name='dimensions')
    code = models.CharField(max_length=80)
    name = models.TextField()
    role = models.CharField(max_length=20,default='key')
    class Meta:
        constraints=[models.UniqueConstraint(fields=['indicator','code'],name='unique_indicator_dimension')]

class DimensionValue(models.Model):
    dimension = models.ForeignKey(Dimension,on_delete=models.CASCADE,related_name='values')
    code = models.CharField(max_length=250)
    label = models.TextField()
    class Meta:
        constraints=[models.UniqueConstraint(fields=['dimension','code'],name='unique_dimension_value')]

class SourceFile(models.Model):
    sha256 = models.CharField(max_length=64,unique=True)
    filename = models.TextField()
    original_path = models.TextField()
    size = models.PositiveIntegerField()
    header_id = models.CharField(max_length=80)
    dataset_id = models.CharField(max_length=80)
    prepared = models.CharField(max_length=80,blank=True)
    metadata = models.JSONField(default=dict)
    created = models.DateTimeField(auto_now_add=True)

class ImportRun(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20,default='running')
    filenames = models.JSONField(default=list)
    added = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    details = models.JSONField(default=list)
    message = models.TextField(blank=True)
    class Meta: ordering=['-created']

class Observation(models.Model):
    indicator = models.ForeignKey(Indicator,on_delete=models.CASCADE,related_name='observations')
    territory = models.ForeignKey(Territory,on_delete=models.PROTECT)
    period = models.ForeignKey(Period,on_delete=models.PROTECT)
    dimension_key = models.CharField(max_length=64)
    dimensions = models.JSONField(default=dict)
    dimension_labels = models.JSONField(default=dict)
    # Точное десятичное представление в TEXT: SQLite NUMERIC может преобразовать Decimal в float.
    numeric_text = models.TextField(null=True,blank=True)
    raw_value = models.TextField(blank=True)
    status = models.JSONField(default=dict)
    attributes = models.JSONField(default=dict)
    source = models.ForeignKey(SourceFile,on_delete=models.PROTECT)
    last_import = models.ForeignKey(ImportRun,on_delete=models.PROTECT)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['indicator','territory','period','dimension_key'],name='unique_observation_full_key')]
        indexes=[models.Index(fields=['indicator','period','territory']),models.Index(fields=['territory','period'])]
    @property
    def number(self): return Decimal(self.numeric_text) if self.numeric_text is not None else None
    @property
    def display(self): return self.raw_value if self.raw_value else 'нет данных'
    @property
    def dimensions_display(self):
        return '; '.join(f'{k}: {v}' for k,v in self.dimension_labels.items())
