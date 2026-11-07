"""Frozen compatibility shim for historical migration 0002 only.
Runtime models use the standard DecimalField. Do not import this in application code.
"""
from django.db import models
class ExactNumericTextField(models.TextField):
    def db_type(self, connection):return 'numeric'
