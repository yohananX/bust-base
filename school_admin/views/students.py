"""Student management views for school admin portal."""

from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.dateparse import parse_date

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from accounts.utils import generate_password, generate_username, unique_username
from students.models import Student, SchoolClass, ClassEnrollment, StudentGuardianLink
from students.utils import generate_admission_number, find_or_create_parent
from core.models import AcademicSession, Term
from fees.models import Invoice, Payment


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
            current_enrollment = next(
                (e for e in s.enrollments.all() if e.is_current), None
            )
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

        from fees.selectors import invoices_with_balance
        invoices = invoices_with_balance(invoices)

        current_enrollment = ClassEnrollment.objects.filter(
            student=student, is_current=True
        ).select_related('school_class').first()

        class_total_amount = Decimal('0.00')
        if current_enrollment:
            from fees.models import FeeCategory, FeeStructure
            from django.db.models import Sum
            from fees.generation import effective_fee_structures
            from core.models import Term
            from fees.utils import resolve_student_type

            current_term = Term.objects.filter(school=school, is_current=True).first()
            if current_term:
                student_type = resolve_student_type(student, current_term.session)
                structures = effective_fee_structures(
                    school, current_enrollment.school_class, current_term,
                    student_type=student_type, student=student, session=current_term.session
                )
                class_total_amount = sum((fs.amount for fs in structures), Decimal('0.00'))

        invoice_less_payments = Payment.objects.filter(
            student=student, invoice__isnull=True,
        ).order_by('-paid_on')

        context = {
            'student': student,
            'enrollments': enrollments,
            'guardian_links': guardian_links,
            'invoices': invoices,
            'invoice_less_payments': invoice_less_payments,
            'parents': User.objects.filter(school=school, role=Roles.PARENT, is_active=True),
            'classes': SchoolClass.objects.filter(school=school, is_active=True),
            'sessions': AcademicSession.objects.filter(school=school),
            'current_enrollment': current_enrollment,
            'class_total_amount': class_total_amount,
        }
        return render(request, 'school_admin/student_detail.html', context)


def _sanitize_username(first_name, last_name):
    """Generate a username from first and last name, sanitized."""
    return generate_username(first_name, last_name)


class StudentCreateView(RoleRequiredMixin, View):
    """Create a new student with optional class enrollment."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        sessions = AcademicSession.objects.filter(school=school)
        context = {
            'classes': classes,
            'sessions': sessions,
            'is_edit': False,
        }
        return render(request, 'school_admin/student_form.html', context)

    def post(self, request):
        school = request.school
        date_of_birth = request.POST.get('date_of_birth')
        gender = request.POST.get('gender')
        admission_date = request.POST.get('admission_date')
        status = request.POST.get('status', 'ACTIVE')
        class_id = request.POST.get('class_id')
        session_id = request.POST.get('session_id')

        # Validate required student fields
        if not all([date_of_birth, gender, admission_date]):
            messages.error(request, 'All student fields are required.')
            return redirect('school_admin:student_create')

        try:
            with transaction.atomic():
                # --- Create new user ---
                first_name = request.POST.get('first_name', '').strip()
                middle_name = request.POST.get('middle_name', '').strip()
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
                password = generate_password(8)

                user = User.objects.create_user(
                    username=username_input,
                    email=email,
                    password=password,
                    first_name=first_name,
                    middle_name=middle_name,
                    last_name=last_name,
                    role=Roles.STUDENT,
                    school=school,
                    phone_number=phone_number,
                    must_change_password=True,
                )
                request.session[f'credential_slip_{user.pk}'] = password

                messages.success(
                    request,
                    f'Student "{user.get_full_name()}" created successfully.',
                )

                # Determine school_class for admission number generation
                school_class = None
                if class_id:
                    school_class = SchoolClass.objects.filter(
                        school=school, pk=class_id
                    ).first()

                # Auto-generate sequential admission number
                admission_number = generate_admission_number(
                    school, school_class
                )

                # Create student record
                student = Student(
                    school=school,
                    user=user,
                    admission_number=admission_number,
                    date_of_birth=parse_date(date_of_birth),
                    gender=gender,
                    admission_date=parse_date(admission_date),
                    status=status,
                    state_of_origin=request.POST.get('state_of_origin', '').strip(),
                    local_government_area=request.POST.get('local_government_area', '').strip(),
                )
                student.full_clean()
                student.save()

                # Attach uploaded passport to student and user
                uploaded = request.FILES.get('passport')
                if uploaded:
                    student.passport = uploaded
                    student.save(update_fields=['passport'])
                    student.user.passport = uploaded
                    student.user.save(update_fields=['passport'])

                # Auto-enroll if class and session provided
                if class_id and session_id:
                    if school_class is None:
                        school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
                    session = get_object_or_404(AcademicSession, school=school, pk=session_id)
                    ClassEnrollment.objects.create(
                        school=school,
                        student=student,
                        school_class=school_class,
                        session=session,
                        is_current=True,
                    )
                    from fees.generation import generate_invoice_for_current_term
                    generate_invoice_for_current_term(student)

                # --- Optional parent/guardian creation ---
                guardian_index = 0
                while True:
                    name = request.POST.get(f'guardian_{guardian_index}_name', '').strip()
                    email = request.POST.get(f'guardian_{guardian_index}_email', '').strip()
                    phone = request.POST.get(f'guardian_{guardian_index}_phone', '').strip()
                    relationship = request.POST.get(f'guardian_{guardian_index}_relationship', 'GUARDIAN')
                    occupation = request.POST.get(f'guardian_{guardian_index}_occupation', '').strip()
                    address = request.POST.get(f'guardian_{guardian_index}_address', '').strip()
                    authorized_pickup_person = request.POST.get(f'guardian_{guardian_index}_authorized_pickup_person', '').strip()

                    if not name and not email and not phone:
                        break

                    if name:
                        parent_user = find_or_create_parent(
                            school, name, email=email, phone=phone, relationship=relationship
                        )
                        StudentGuardianLink.objects.create(
                            school=school,
                            student=student,
                            guardian=parent_user,
                            relationship=relationship,
                            is_primary_contact=(guardian_index == 0),
                            occupation=occupation,
                            address=address,
                            authorized_pickup_person=authorized_pickup_person,
                        )

                    guardian_index += 1

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
                user.middle_name = request.POST.get('user_middle_name', '').strip()
                user.last_name = request.POST.get('user_last_name', '').strip()
                user.email = request.POST.get('user_email', '').strip()
                user.phone_number = request.POST.get('user_phone_number', '').strip()
                user.save()

                student.admission_number = admission_number
                student.date_of_birth = parse_date(date_of_birth)
                student.gender = gender
                student.admission_date = parse_date(admission_date)
                student.status = status
                student.state_of_origin = request.POST.get('state_of_origin', '').strip()
                student.local_government_area = request.POST.get('local_government_area', '').strip()
                student.save()

                # Attach uploaded passport to student and user
                uploaded = request.FILES.get('passport')
                if uploaded:
                    student.passport = uploaded
                    student.save(update_fields=['passport'])
                    student.user.passport = uploaded
                    student.user.save(update_fields=['passport'])

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
                        enrollment = ClassEnrollment.objects.filter(
                            student=student, session=new_session
                        ).first()
                        if enrollment:
                            enrollment.school_class = new_class
                            enrollment.is_current = True
                            enrollment.save()
                        else:
                            ClassEnrollment.objects.create(
                                school=school,
                                student=student,
                                school_class=new_class,
                                session=new_session,
                                is_current=True,
                            )
                        from fees.generation import generate_invoice_for_current_term
                        generate_invoice_for_current_term(student)

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

                enrollment = ClassEnrollment.objects.filter(
                    student=student, session=session
                ).first()
                if enrollment:
                    enrollment.school_class = school_class
                    enrollment.is_current = True
                    enrollment.save()
                else:
                    ClassEnrollment.objects.create(
                        school=school,
                        student=student,
                        school_class=school_class,
                        session=session,
                        is_current=True,
                    )

                from fees.generation import generate_invoice_for_current_term
                generated = generate_invoice_for_current_term(student)

            if generated:
                messages.success(
                    request,
                    f'{student.user.get_full_name()} moved to {school_class.name} '
                    f'({session.name}). Term invoice generated.',
                )
            else:
                messages.success(
                    request,
                    f'{student.user.get_full_name()} moved to {school_class.name} '
                    f'({session.name}).',
                )

        except Exception as e:
            messages.error(request, f'Error changing class: {e}')

        return redirect('school_admin:student_detail', pk=student.pk)


class StudentGuardianCreateView(RoleRequiredMixin, View):
    """Create a new guardian/parent account and link it to a student."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)

        first_name = request.POST.get('guardian_first_name', '').strip()
        last_name = request.POST.get('guardian_last_name', '').strip()
        email = request.POST.get('guardian_email', '').strip()
        phone_number = request.POST.get('guardian_phone_number', '').strip()
        relationship = request.POST.get('relationship', 'GUARDIAN')
        occupation = request.POST.get('guardian_occupation', '').strip()
        address = request.POST.get('guardian_address', '').strip()
        authorized_pickup_person = request.POST.get('guardian_authorized_pickup_person', '').strip()
        is_primary_contact = request.POST.get('is_primary_contact') == 'on'

        if not first_name or not last_name:
            messages.error(request, 'Guardian first and last name are required.')
            return redirect('school_admin:student_detail', pk=student.pk)

        try:
            with transaction.atomic():
                username = unique_username(first_name, last_name)
                password = generate_password(8)

                guardian = User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone_number=phone_number,
                    role=Roles.PARENT,
                    school=school,
                    password=password,
                    must_change_password=True,
                )

                uploaded = request.FILES.get('guardian_passport')
                if uploaded:
                    guardian.passport = uploaded
                    guardian.save(update_fields=['passport'])

                if is_primary_contact:
                    StudentGuardianLink.objects.filter(student=student).update(is_primary_contact=False)

                link = StudentGuardianLink(
                    student=student,
                    guardian=guardian,
                    relationship=relationship,
                    is_primary_contact=is_primary_contact,
                    occupation=occupation,
                    address=address,
                    authorized_pickup_person=authorized_pickup_person,
                    school=school,
                )
                link.full_clean()
                link.save()
                request.session[f'credential_slip_{guardian.pk}'] = password

                messages.success(
                    request,
                    f'Guardian "{guardian.get_full_name()}" added successfully.',
                )
        except (IntegrityError, ValidationError) as e:
            messages.warning(request, f'Could not add guardian: {e}')

        return redirect('school_admin:student_detail', pk=student.pk)


class StudentPasswordChangeView(RoleRequiredMixin, View):
    """Change a student's user account password."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)
        context = {'student': student}
        return render(request, 'school_admin/student_password_change.html', context)

    def post(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)
        user = student.user

        action = request.POST.get('action', '')
        new_password = request.POST.get('new_password', '').strip()

        if action == 'auto_generate':
            password = generate_password(8)
        elif new_password:
            password = new_password
        else:
            messages.error(request, 'Please enter a new password or use auto-generate.')
            return redirect('school_admin:student_password_change', pk=pk)

        user.set_password(password)
        user.must_change_password = True
        user.save(update_fields=['password', 'must_change_password'])
        request.session[f'credential_slip_{user.pk}'] = password

        name = user.get_full_name() or user.username
        messages.success(request, f'Password has been changed for {name}.')
        return redirect('school_admin:credential_slip', pk=user.pk)


class StudentGuardianLinkDeleteView(RoleRequiredMixin, View):
    """Remove a guardian link from a student."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        link = get_object_or_404(StudentGuardianLink, pk=pk, student__school=request.school)
        student_id = link.student_id
        link.delete()
        messages.success(request, 'Guardian link removed.')
        return redirect('school_admin:student_detail', pk=student_id)


class StudentGuardianUpdateView(RoleRequiredMixin, View):
    """Edit an existing guardian link and its parent user details."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        link = get_object_or_404(StudentGuardianLink, pk=pk, student__school=school)
        student = link.student
        guardian = link.guardian

        guardian.first_name = request.POST.get('guardian_first_name', '').strip()
        guardian.last_name = request.POST.get('guardian_last_name', '').strip()
        guardian.email = request.POST.get('guardian_email', '').strip()
        guardian.phone_number = request.POST.get('guardian_phone_number', '').strip()
        guardian.save(update_fields=['first_name', 'last_name', 'email', 'phone_number'])

        link.relationship = request.POST.get('relationship', link.relationship)
        link.occupation = request.POST.get('guardian_occupation', '').strip()
        link.address = request.POST.get('guardian_address', '').strip()
        link.authorized_pickup_person = request.POST.get('guardian_authorized_pickup_person', '').strip()
        link.is_primary_contact = request.POST.get('is_primary_contact') == 'on'

        if link.is_primary_contact:
            StudentGuardianLink.objects.filter(student=student).exclude(pk=link.pk).update(is_primary_contact=False)

        link.save()
        messages.success(request, 'Guardian updated successfully.')
        return redirect('school_admin:student_detail', pk=student.pk)
