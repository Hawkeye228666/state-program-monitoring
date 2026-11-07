"""Exact decimal storage with a stable string API on both database backends."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import models

class ExactNumericTextField(models.TextField):
    description = 'Exact decimal: NUMERIC on PostgreSQL, TEXT on SQLite'

    def db_type(self, connection):
        return 'numeric' if connection.vendor == 'postgresql' else 'text'

    def from_db_value(self, value, expression, connection):
        return None if value is None else str(value)

    def get_prep_value(self, value):
        if value is None:
            return None
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            raise ValidationError('A finite decimal is required.')
        return str(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        value = self.get_prep_value(value)
        if connection.vendor == 'postgresql' and value is not None:
            return Decimal(value)
        return value
