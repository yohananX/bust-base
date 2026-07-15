"""Student management views for school admin portal."""
import re
import secrets

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils.dateparse import parse_date

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from students.models import Student, SchoolClass, ClassEnrollment, StudentGuardianLink
from core.models import AcademicSession
from fees.models import Invoice


class StudentListView(RoleRequiredMixin, View):
    """List all students in the admin's school with search and filter."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        students = Student.objects.filter(
            school=school
        ).select_related('user').prefetch_related(
            'enrollments__school_class'
        )

        # Search by name / admission number
        q = request.GET.get('q', '')
        if q:
            students = students.filter(
                Q(user__first_name__icontains=q) |
                Q(user__last_name__icontains=q) |
                Q(admission_number__icontains=q)
            )

        # Filter by class
        class_id = request.GET.get('class_id', '')
        if class_id:
            students = students.filter(
                enrollments__school_class_id=class_id,
                enrollments__is_current=True,
            )

        # Filter by status
        status = request.GET.get('status', '')
        if status:
            students = students.filter(status=status)

        students = students.distinct()

        # Annotate current class
        for s in students:
            current_enrollment = s.enrollments.filter(is_current=True).first()
            s.current_class = current_enrollment.school_class if current_enrollment else None

        classes = SchoolClass.objects.filter(school=school, is_active=True)

        context = {
            'students': students,
            'classes': classes,
            'q': q,
            'filter_class_id': class_id,
            'filter_status': status,
            'status_choices': Student.STATUS_CHOICES,
        }
        return render(request, 'school_admin/student_list.html', context)


class StudentDetailView(RoleRequiredMixin, View):
    """Student detail with enrollment history, guardians, invoices."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)

        enrollments = ClassEnrollment.objects.filter(
            student=student
        ).select_related('school_class', 'session').order_by('-session__start_date')

        guardian_links = StudentGuardianLink.objects.filter(
            student=student
        ).select_related('guardian')

        invoices = Invoice.objects.filter(
            student=student
        ).select_related('term').prefetch_related('payments')

        context = {
            'student': student,
            'enrollments': enrollments,
            'guardian_links': guardian_links,
            'invoices': invoices,
            'parents': User.objects.filter(school=school, role=Roles.PARENT, is_active=True),
            'classes': SchoolClass.objects.filter(school=school, is_active=True),
            'sessions': AcademicSession.objects.filter(school=school),
        }
        return render(request, 'school_admin/student_detail.html', context)


def _sanitize_username(first_name, last_name):
    """Generate a username from first and last name, sanitized.

    Lowercase, replace spaces with dots, strip non-alphanumeric characters
    (except dots).
    """
    base = f"{first_name.strip()}.{last_name.strip()}"
    base = base.lower().replace(' ', '.')
    base = re.sub(r'[^a-z0-9.]', '', base)
    return base


class StudentCreateView(RoleRequiredMixin, View):
    """Create a new student with optional class enrollment."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        sessions = AcademicSession.objects.filter(school=school)
        users = User.objects.filter(school=school, role=Roles.STUDENT, is_active=True)
        users_with_no_student = users.exclude(
            pk__in=Student.objects.filter(school=school).values_list('user_id', flat=True)
        )
        context = {
            'classes': classes,
            'sessions': sessions,
            'users': users,
            'users_with_no_student': users_with_no_student,
            'is_edit': False,
        }
        return render(request, 'school_admin/student_form.html', context)

    def post(self, request):
        school = request.school
        user_mode = request.POST.get('user_mode', 'existing')
        admission_number = request.POST.get('admission_number')
        date_of_birth = request.POST.get('date_of_birth')
        gender = request.POST.get('gender')
        admission_date = request.POST.get('admission_date')
        status = request.POST.get('status', 'ACTIVE')
        class_id = request.POST.get('class_id')
        session_id = request.POST.get('session_id')

        # Validate required student fields
        if not all([admission_number, date_of_birth, gender, admission_date]):
            messages.error(request, 'All student fields are required.')
            return redirect('school_admin:student_create')

        # Validate unique admission number
        if Student.objects.filter(school=school, admission_number=admission_number).exists():
            messages.error(request, 'A student with this admission number already exists.')
            return redirect('school_admin:student_create')

        try:
            with transaction.atomic():
                if user_mode == 'new':
                    # --- Create new user ---
                    first_name = request.POST.get('first_name', '').strip()
                    last_name = request.POST.get('last_name', '').strip()
                    email = request.POST.get('new_email', '').strip()
                    phone_number = request.POST.get('new_phone_number', '').strip()
                    username_input = request.POST.get('new_username', '').strip()

                    if not first_name or not last_name:
                        messages.error(request, 'First name and last name are required for new users.')
                        return redirect('school_admin:student_create')

                    # Auto-generate username if empty
                    if not username_input:
                        username_input = _sanitize_username(first_name, last_name)

                    # Ensure unique username
                    base_username = username_input
                    counter = 1
                    while User.objects.filter(username=username_input).exists():
                        username_input = f"{base_username}{counter}"
                        counter += 1

                    # Generate random password
                    password = secrets.token_urlsafe(6)

                    user = User.objects.create_user(
                        username=username_input,
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                        role=Roles.STUDENT,
                        school=school,
                        phone_number=phone_number,
                    )

                    messages.success(
                        request,
                        f'User "{user.get_full_name() or user.username}" created. '
                        f'Password: {password}',
                    )
                else:
                    # --- Use existing user ---
                    user_id = request.POST.get('user')
                    if not user_id:
                        messages.error(request, 'Please select a user.')
                        return redirect('school_admin:student_create')
                    user = get_object_or_404(
                        User, school=school, pk=user_id, role=Roles.STUDENT
                    )
                    password = None

                # Create student record
                student = Student.objects.create(
                    school=school,
                    user=user,
                    admission_number=admission_number,
                    date_of_birth=parse_date(date_of_birth),
                    gender=gender,
                    admission_date=parse_date(admission_date),
                    status=status,
                )

                # Auto-enroll if class and session provided
                if class_id and session_id:
                    school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
                    session = get_object_or_404(AcademicSession, school=school, pk=session_id)
                    ClassEnrollment.objects.create(
                        school=school,
                        student=student,
                        school_class=school_class,
                        session=session,
                        is_current=True,
                    )

                # --- Optional parent/guardian creation ---
                parent_name = request.POST.get('parent_name', '').strip()
                parent_email = request.POST.get('parent_email', '').strip()
                parent_phone = request.POST.get('parent_phone', '').strip()

                if parent_name or parent_email or parent_phone:
                    # Split parent name into first/last
                    parent_name_parts = parent_name.split(None, 1)
                    parent_first = parent_name_parts[0] if parent_name_parts else ''
                    parent_last = parent_name_parts[1] if len(parent_name_parts) > 1 else ''

                    if parent_first:
                        # Generate parent username
                        parent_username = _sanitize_username(parent_first, parent_last) if parent_last else parent_first.lower()
                        parent_base = parent_username
                        parent_counter = 1
                        while User.objects.filter(username=parent_username).exists():
                            parent_username = f"{parent_base}{parent_counter}"
                            parent_counter += 1

                        parent_password = secrets.token_urlsafe(6)
                        parent_user = User.objects.create_user(
                            username=parent_username,
                            email=parent_email,
                            password=parent_password,
                            first_name=parent_first,
                            last_name=parent_last,
                            role=Roles.PARENT,
                            school=school,
                            phone_number=parent_phone,
                        )

                        # Link parent as guardian
                        relationship = request.POST.get('parent_relationship', 'GUARDIAN')
                        StudentGuardianLink.objects.create(
                            student=student,
                            guardian=parent_user,
                            relationship=relationship,
                            is_primary_contact=True,
                            school=school,
                        )

                        messages.success(
                            request,
                            f'Parent "{parent_user.get_full_name() or parent_user.username}" '
                            f'created and linked. Password: {parent_password}',
                        )

                messages.success(request, f'Student "{user.get_full_name()}" created successfully.')
                return redirect('school_admin:student_detail', pk=student.pk)

        except Exception as e:
            messages.error(request, f'Error creating student: {e}')
            return redirect('school_admin:student_create')


class StudentEditView(RoleRequiredMixin, View):
    """Edit an existing student's details and optionally change enrollment."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        sessions = AcademicSession.objects.filter(school=school)
        existing_enrollment = ClassEnrollment.objects.filter(
            student=student, is_current=True
        ).first()
        guardian_links = StudentGuardianLink.objects.filter(
            student=student
        ).select_related('guardian')

        context = {
            'student': student,
            'classes': classes,
            'sessions': sessions,
            'existing_enrollment': existing_enrollment,
            'guardian_links': guardian_links,
            'is_edit': True,
        }
        return render(request, 'school_admin/student_form.html', context)

    def post(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)

        admission_number = request.POST.get('admission_number')
        date_of_birth = request.POST.get('date_of_birth')
        gender = request.POST.get('gender')
        admission_date = request.POST.get('admission_date')
        status = request.POST.get('status', student.status)
        class_id = request.POST.get('class_id')
        session_id = request.POST.get('session_id')

        # Validate unique admission number (exclude self)
        if Student.objects.filter(
            school=school, admission_number=admission_number
        ).exclude(pk=student.pk).exists():
            messages.error(request, 'Another student already has this admission number.')
            return redirect('school_admin:student_edit', pk=student.pk)

        try:
            with transaction.atomic():
                # Update linked user fields
                user = student.user
                user.first_name = request.POST.get('user_first_name', '').strip()
                user.last_name = request.POST.get('user_last_name', '').strip()
                user.email = request.POST.get('user_email', '').strip()
                user.phone_number = request.POST.get('user_phone_number', '').strip()
                user.save()

                student.admission_number = admission_number
                student.date_of_birth = parse_date(date_of_birth)
                student.gender = gender
                student.admission_date = parse_date(admission_date)
                student.status = status
                student.save()

                # Handle enrollment change
                if class_id and session_id:
                    current_enrollment = ClassEnrollment.objects.filter(
                        student=student, is_current=True
                    ).first()

                    new_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
                    new_session = get_object_or_404(AcademicSession, school=school, pk=session_id)

                    should_enroll = (
                        not current_enrollment
                        or current_enrollment.school_class_id != new_class.pk
                        or current_enrollment.session_id != new_session.pk
                    )

                    if should_enroll:
                        ClassEnrollment.objects.create(
                            school=school,
                            student=student,
                            school_class=new_class,
                            session=new_session,
                            is_current=True,
                        )

                messages.success(
                    request,
                    f'Student "{student.user.get_full_name()}" updated successfully.',
                )
                return redirect('school_admin:student_detail', pk=student.pk)

        except Exception as e:
            messages.error(request, f'Error updating student: {e}')
            return redirect('school_admin:student_edit', pk=student.pk)


class StudentDeleteView(RoleRequiredMixin, View):
    """Delete a student with confirmation and related-record warnings."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)

        # Gather related record counts
        related = {
            'enrollments': ClassEnrollment.objects.filter(student=student).count(),
            'guardian_links': StudentGuardianLink.objects.filter(student=student).count(),
            'invoices': Invoice.objects.filter(student=student).count(),
        }
        has_related = any(count > 0 for count in related.values())

        context = {
            'student': student,
            'related': related,
            'has_related': has_related,
        }
        return render(request, 'school_admin/student_confirm_delete.html', context)

    def post(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)
        name = student.user.get_full_name() or student.user.username

        try:
            with transaction.atomic():
                student.delete()
            messages.success(request, f'Student "{name}" has been deleted.')
        except Exception as e:
            messages.error(request, f'Error deleting student: {e}')

        return redirect('school_admin:student_list')


class StudentChangeClassView(RoleRequiredMixin, View):
    """Change a student's current class by creating a new enrollment."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)

        class_id = request.POST.get('class_id')
        session_id = request.POST.get('session_id')

        if not class_id or not session_id:
            messages.error(request, 'Both class and session are required.')
            return redirect('school_admin:student_detail', pk=student.pk)

        try:
            with transaction.atomic():
                school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
                session = get_object_or_404(AcademicSession, school=school, pk=session_id)

                ClassEnrollment.objects.create(
                    school=school,
                    student=student,
                    school_class=school_class,
                    session=session,
                    is_current=True,
                )

            messages.success(
                request,
                f'{student.user.get_full_name()} moved to {school_class.name} '
                f'({session.name}).',
            )

        except Exception as e:
            messages.error(request, f'Error changing class: {e}')

        return redirect('school_admin:student_detail', pk=student.pk)


class StudentGuardianLinkCreateView(RoleRequiredMixin, View):
    """Link a guardian (parent) to a student."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request):
        student_id = request.POST.get('student_id')
        guardian_id = request.POST.get('guardian_id')
        relationship = request.POST.get('relationship')
        is_primary_contact = request.POST.get('is_primary_contact') == 'on'

        student = get_object_or_404(Student, school=request.school, pk=student_id)
        guardian = get_object_or_404(
            User, school=request.school, role=Roles.PARENT,
            pk=guardian_id, is_active=True,
        )

        try:
            with transaction.atomic():
                if is_primary_contact:
                    StudentGuardianLink.objects.filter(student=student).update(is_primary_contact=False)
                StudentGuardianLink.objects.create(
                    student=student,
                    guardian=guardian,
                    relationship=relationship,
                    is_primary_contact=is_primary_contact,
                    school=request.school,
                )
            messages.success(request, 'Guardian linked successfully.')
        except IntegrityError:
            messages.warning(request, 'This guardian is already linked to this student.')

        return redirect('school_admin:student_detail', pk=student_id)


class StudentGuardianLinkDeleteView(RoleRequiredMixin, View):
    """Remove a guardian link from a student."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        link = get_object_or_404(StudentGuardianLink, pk=pk, student__school=request.school)
        student_id = link.student_id
        link.delete()
        messages.success(request, 'Guardian link removed.')
        return redirect('school_admin:student_detail', pk=student_id)
