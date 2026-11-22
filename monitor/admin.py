from django.contrib import admin
from .models import Program, Indicator, Territory, Period, Dimension, DimensionValue, SourceFile, ImportRun, Observation
from .models import MappingProfile,ClassifierSnapshot,RelatedSeries,ImportJob

admin.site.register(MappingProfile)
admin.site.register(RelatedSeries)

@admin.register(ClassifierSnapshot)
class ClassifierAdmin(admin.ModelAdmin):
    readonly_fields=['source','concept','identity','digest','codes']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False


@admin.register(Program, Indicator, Territory, Period, Dimension, DimensionValue)
class MetadataAdmin(admin.ModelAdmin):
    list_per_page = 50


@admin.register(SourceFile, ImportRun, Observation)
class EvidenceAdmin(admin.ModelAdmin):
    """Evidence is imported through the loader, never manually rewritten in admin."""
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
