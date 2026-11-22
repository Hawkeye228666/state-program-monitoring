from django import forms
from django.core.validators import URLValidator
from .models import Program

class ProgramForm(forms.ModelForm):
    source_urls=forms.CharField(label='Ссылки на источники (по одной в строке)',widget=forms.Textarea,required=False)
    class Meta:
        model=Program
        fields=['name','slug','summary','schedule']
        labels={'name':'Название','slug':'Уникальный идентификатор (латиница)','summary':'Описание','schedule':'Сведения о сроках (только подтверждённые)'}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for key in ('summary','schedule'):self.fields[key].required=False
        if self.instance.pk:self.fields['source_urls'].initial='\n'.join(s['url'] for s in self.instance.sources)
    def clean_source_urls(self):
        urls=self.cleaned_data['source_urls'].splitlines()
        for url in urls:
            if url.strip():URLValidator(schemes=['http','https'])(url.strip())
        return [{'title':u.strip(),'url':u.strip()} for u in urls if u.strip()]
    def clean_slug(self):
        slug=self.cleaned_data['slug']
        if slug=='new':raise forms.ValidationError('Идентификатор new зарезервирован маршрутом создания программы.')
        return slug
    def save(self,commit=True):
        self.instance.sources=self.cleaned_data['source_urls']
        return super().save(commit=commit)
