"""Credential slip views for school admin portal.

Printable onboarding cards (username + one-time password) for newly
created or batch-reset users. Raw passwords live ONLY in the session,
keyed by user pk (`credential_slip_<pk>`), and are never persisted
to the database, files, or logs.
"""
import secrets
import string

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User


def _random_password(length=10):
    """Cryptographically random alphanumeric password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _session_key(pk):
    return f'credential_slip_{pk}'


def _clear_slip_keys(session):
    """Remove every credential-slip key from the session."""
    for key in [k for k in session.keys() if k.startswith('credential_slip_')]:
        del session[key]


class CredentialSlipView(RoleRequiredMixin, View):
    """Show the printable credential slip for a single user."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        user = get_object_or_404(User, school=request.school, pk=pk)
        # Pop the key so a refresh (or a later visit) shows the expired state.
        raw_password = request.session.pop(_session_key(pk), None)
        slips = []
        if raw_password is not None:
            slips = [{'user': user, 'password': raw_password}]
        # Reuse the same printable layout as the batch print page.
        return render(request, 'school_admin/credential_batch_print.html', {'slips': slips})


class CredentialBatchView(RoleRequiredMixin, View):
    """Choose a group (staff or students) and reset all their passwords."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        context = {
            'staff_count': User.objects.filter(school=school, role=Roles.TEACHER).count(),
            'student_count': User.objects.filter(school=school, role=Roles.STUDENT).count(),
        }
        return render(request, 'school_admin/credential_batch.html', context)

    def post(self, request):
        school = request.school
        group = request.POST.get('group', '')
        if group == 'staff':
            users = list(User.objects.filter(school=school, role=Roles.TEACHER))
            label = 'staff'
        elif group == 'students':
            users = list(User.objects.filter(school=school, role=Roles.STUDENT))
            label = 'students'
        else:
            messages.error(request, 'Please choose a group (Staff or Students).')
            return redirect('school_admin:credential_batch')

        if not users:
            messages.warning(request, f'No {label} found in this school.')
            return redirect('school_admin:credential_batch')

        # Drop stale slips from previous batches so the print page only
        # shows cards for the group we just reset.
        _clear_slip_keys(request.session)

        # Bulk password generation: hash with the cheap MD5 hasher and
        # write one UPDATE. PBKDF2 is deliberately slow (~0.3s per hash),
        # so hashing 400 students with it takes minutes. Django rehashes to
        # PBKDF2 automatically on the user's next successful login, so this
        # is safe for one-time onboarding slips.
        with transaction.atomic():
            pairs = []
            for user in users:
                raw_password = _random_password()
                user.password = make_password(raw_password, hasher='md5')
                user.must_change_password = True
                pairs.append((user, raw_password))
            User.objects.bulk_update(users, ['password', 'must_change_password'])

        for user, raw_password in pairs:
            request.session[_session_key(user.pk)] = raw_password

        messages.success(request, f'Generated new passwords for {len(users)} {label}.')
        return redirect('school_admin:credential_batch_print')


class CredentialBatchPrintView(RoleRequiredMixin, View):
    """Print page: one card per user whose session key exists."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        users = User.objects.filter(
            school=school,
            role__in=[Roles.TEACHER, Roles.STUDENT],
        ).order_by('role', 'last_name', 'first_name')

        slips = []
        for user in users:
            raw_password = request.session.get(_session_key(user.pk))
            if raw_password is not None:
                slips.append({'user': user, 'password': raw_password})

        context = {'slips': slips}
        return render(request, 'school_admin/credential_batch_print.html', context)


class CredentialSingleResetView(RoleRequiredMixin, View):
    """Reset one user's password and show their printable slip."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        user = get_object_or_404(
            User,
            school=request.school,
            pk=pk,
            role__in=[Roles.TEACHER, Roles.STUDENT, Roles.PARENT],
        )
        raw_password = _random_password()
        user.set_password(raw_password)
        user.must_change_password = True
        user.save(update_fields=['password', 'must_change_password'])
        # Drop stale slips so the print page only shows this card.
        _clear_slip_keys(request.session)
        request.session[_session_key(user.pk)] = raw_password
        messages.success(request, f'New password generated for "{user.get_full_name() or user.username}".')
        return redirect('school_admin:credential_slip', pk=user.pk)


class CredentialMemberConfirmView(RoleRequiredMixin, View):
    """Confirm page reached from the member autocomplete before resetting."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        user = get_object_or_404(
            User,
            school=request.school,
            pk=pk,
            role__in=[Roles.TEACHER, Roles.STUDENT, Roles.PARENT],
        )
        return render(request, 'school_admin/credential_member_confirm.html', {'member': user})
