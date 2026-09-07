"""Forms for school_admin generic views."""

from django import forms

from fees.models import FeeCategory


class FeeCategoryForm(forms.ModelForm):
    class Meta:
        model = FeeCategory
        fields = ['name', 'is_compulsory', 'billing_cycle', 'student_type']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'is_compulsory': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'billing_cycle': forms.Select(attrs={'class': 'form-control'}),
            'student_type': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school

    def clean_name(self):
        name = self.cleaned_data['name']
        qs = FeeCategory.objects.filter(school=self.school, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A category with that name already exists.')
        return name
