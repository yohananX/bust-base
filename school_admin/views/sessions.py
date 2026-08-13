"""Session and term management views for school admin portal."""
from datetime import datetime, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import AcademicSession


class SessionListView(RoleRequiredMixin, View):
    """List all academic sessions for the school."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        from core.models import Term
        sessions = AcademicSession.objects.filter(
            school=school
        ).prefetch_related('terms').order_by('-start_date')
        context = {
            'sessions': sessions,
            'current_session': AcademicSession.objects.filter(
                school=school, is_current=True
            ).first(),
            'current_term': Term.objects.filter(
                school=school, is_current=True
            ).first(),
        }
        return render(request, 'school_admin/session_list.html', context)


class SessionCreateView(RoleRequiredMixin, View):
    """Create a session with its three automatic terms."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        return render(request, 'school_admin/session_form.html', {
            'is_edit': False,
        })

    def post(self, request):
        school = request.school
        name = request.POST.get('name', '').strip()
        start_date_str = request.POST.get('start_date', '').strip()
        end_date_str = request.POST.get('end_date', '').strip()

        form_context = {
            'is_edit': False,
            'name': name,
            'start_date': start_date_str,
            'end_date': end_date_str,
        }

        if not all([name, start_date_str, end_date_str]):
            messages.error(request, 'Name, start date, and end date are required.')
            return render(request, 'school_admin/session_form.html', form_context)

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Invalid date.')
            return render(request, 'school_admin/session_form.html', form_context)

        if end_date < start_date:
            messages.error(request, 'End date must be on or after the start date.')
            return render(request, 'school_admin/session_form.html', form_context)

        if AcademicSession.objects.filter(school=school, name=name).exists():
            messages.error(request, 'A session with that name already exists.')
            return render(request, 'school_admin/session_form.html', form_context)

        with transaction.atomic():
            session = AcademicSession.objects.create(
                school=school, name=name,
                start_date=start_date, end_date=end_date,
            )
            total_days = (end_date - start_date).days
            third = max(total_days // 3, 1)

            from core.models import Term
            Term.objects.create(
                school=school, session=session, name='First Term',
                start_date=start_date,
                end_date=start_date + timedelta(days=third),
                is_current=True,
            )
            Term.objects.create(
                school=school, session=session, name='Second Term',
                start_date=start_date + timedelta(days=third + 1),
                end_date=start_date + timedelta(days=2 * third),
                is_current=False,
            )
            Term.objects.create(
                school=school, session=session, name='Third Term',
                start_date=start_date + timedelta(days=2 * third + 1),
                end_date=end_date,
                is_current=False,
            )

        messages.success(request, f'Session "{name}" created with First, Second and Third Term.')
        return redirect('school_admin:session_list')


class SessionSetCurrentView(RoleRequiredMixin, View):
    """Mark a session (and its first term) as current via POST."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        session = get_object_or_404(AcademicSession, school=school, pk=pk)
        session.is_current = True
        session.save()

        first_term = session.terms.order_by('start_date').first()
        if first_term:
            first_term.is_current = True
            first_term.save()

        messages.success(request, f'{session.name} is now the current session.')
        return redirect('school_admin:session_list')


class TermSetCurrentView(RoleRequiredMixin, View):
    """Mark a term as current via POST."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        from core.models import Term
        term = get_object_or_404(Term, school=school, pk=pk)
        term.is_current = True
        term.save()

        session = term.session
        session.is_current = True
        session.save()

        messages.success(request, f'{term.name} is now the current term.')
        return redirect('school_admin:session_list')