"""School settings view for the school admin portal."""
from django.contrib import messages
from django.shortcuts import render, redirect
from django.views.generic.base import View
from PIL import Image

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import School

ALLOWED_LOGO_TYPES = {'image/png', 'image/jpeg', 'image/webp'}
MAX_LOGO_SIZE = 5 * 1024 * 1024


class SchoolSettingsView(RoleRequiredMixin, View):
    """Edit the current school's profile details and logo."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        return render(request, 'school_admin/school_settings.html', {'school': school})

    def post(self, request):
        school = request.school

        school.name = request.POST.get('name', '').strip()
        school.short_code = request.POST.get('short_code', '').strip()
        school.address = request.POST.get('address', '').strip()
        school.phone = request.POST.get('phone', '').strip()
        school.email = request.POST.get('email', '').strip()
        school.principal_name = request.POST.get('principal_name', '').strip()
        school.bank_name = request.POST.get('bank_name', '').strip()
        school.account_name = request.POST.get('account_name', '').strip()
        school.account_number = request.POST.get('account_number', '').strip()

        for field in ('test_max_score', 'exam_max_score'):
            raw = request.POST.get(field, '').strip()
            if not raw.isdigit() or int(raw) < 1 or int(raw) > 32767:
                messages.error(request, 'Score maxima must be whole numbers between 1 and 32767.')
                return render(request, 'school_admin/school_settings.html', {'school': school})
            setattr(school, field, int(raw))

        if not school.name:
            messages.error(request, 'School name is required.')
            return render(request, 'school_admin/school_settings.html', {'school': school})

        if School.objects.filter(short_code=school.short_code).exclude(pk=school.pk).exists():
            messages.error(request, 'That short code is already in use.')
            return render(request, 'school_admin/school_settings.html', {'school': school})

        logo = request.FILES.get('logo')
        if logo:
            if logo.content_type not in ALLOWED_LOGO_TYPES:
                messages.error(request, 'Logo must be a PNG, JPG or WebP image.')
                return render(request, 'school_admin/school_settings.html', {'school': school})
            if logo.size > MAX_LOGO_SIZE:
                messages.error(request, 'Logo must be 5MB or smaller.')
                return render(request, 'school_admin/school_settings.html', {'school': school})
            try:
                image = Image.open(logo)
                image.verify()
                logo.seek(0)
            except Exception:
                messages.error(request, 'That file is not a valid image.')
                return render(request, 'school_admin/school_settings.html', {'school': school})

            old_logo = school.logo
            school.logo = logo
            school.save()
            if old_logo and old_logo.name and old_logo.name != school.logo.name:
                old_logo.delete(save=False)
        else:
            school.save()

        messages.success(request, 'School settings updated.')
        return redirect('school_admin:school_settings')