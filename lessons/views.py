"""School admin views for the Extra Lessons / Summer School module."""

from decimal import Decimal

from django.contrib import messages as dj_messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from accounts.utils import generate_password, generate_username, parse_full_name
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from students.utils import generate_admission_number, find_or_create_parent
from core.models import AcademicSession

from .models import (
    LessonClass,
    LessonEnrollment,
    LessonPeriod,
    LessonTeacherAssignment,
)


def messages_error(request, text):
    dj_messages.error(request, text)


def messages_success(request, text):
    dj_messages.success(request, text)


class PeriodListView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        periods = LessonPeriod.objects.filter(school=school).annotate(
            class_count=Count('lesson_classes'),
        )
        q = request.GET.get('q', '').strip()
        if q:
            periods = periods.filter(name__icontains=q)
        context = {
            'periods': periods,
            'q': q,
        }
        return render(request, 'lessons/admin/period_list.html', context)


class PeriodFormView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk=None):
        period = None
        if pk:
            period = get_object_or_404(LessonPeriod, school=request.school, pk=pk)
        context = {'period': period, 'is_edit': pk is not None}
        return render(request, 'lessons/admin/period_form.html', context)

    def post(self, request, pk=None):
        school = request.school
        period = None
        if pk:
            period = get_object_or_404(LessonPeriod, school=school, pk=pk)

        name = request.POST.get('name', '').strip()
        start_date = request.POST.get('start_date', '').strip()
        end_date = request.POST.get('end_date', '').strip()
        status = request.POST.get('status', LessonPeriod.Status.DRAFT)
        description = request.POST.get('description', '').strip()

        if not name or not start_date or not end_date:
            messages_error(request, 'Name, start date and end date are required.')
            return redirect('lessons:period_form', pk) if pk else redirect('lessons:period_new')

        qs = LessonPeriod.objects.filter(school=school, name=name)
        if pk:
            qs = qs.exclude(pk=pk)
        if qs.exists():
            messages_error(request, f'A period named "{name}" already exists.')
            return redirect('lessons:period_form', pk) if pk else redirect('lessons:period_new')

        defaults = {
            'name': name,
            'start_date': start_date,
            'end_date': end_date,
            'status': status,
            'description': description,
        }
        if period:
            LessonPeriod.objects.filter(pk=period.pk).update(**defaults)
            messages_success(request, f'Period "{name}" updated.')
        else:
            LessonPeriod.objects.create(school=school, **defaults)
            messages_success(request, f'Period "{name}" created.')
        return redirect('lessons:period_list')


class PeriodCloseView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        period = get_object_or_404(LessonPeriod, school=request.school, pk=pk)
        period.status = LessonPeriod.Status.CLOSED
        period.save()
        messages_success(request, f'Period "{period.name}" closed.')
        return redirect('lessons:period_list')


class ClassListView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        classes = LessonClass.objects.filter(school=school).select_related('period').annotate(
            enrolled_count=Count('enrollments'),
        )
        period_id = request.GET.get('period', '')
        q = request.GET.get('q', '').strip()
        if period_id:
            classes = classes.filter(period_id=period_id)
        if q:
            classes = classes.filter(
                Q(name__icontains=q)
                | Q(period__name__icontains=q)
                | Q(enrollments__student__user__first_name__icontains=q)
                | Q(enrollments__student__user__last_name__icontains=q)
                | Q(enrollments__parent_name__icontains=q)
                | Q(enrollments__external_name__icontains=q)
            ).distinct()
        periods = LessonPeriod.objects.filter(school=school).order_by('-start_date')
        context = {
            'classes': classes,
            'periods': periods,
            'period_id': period_id,
            'q': q,
        }
        return render(request, 'lessons/admin/class_list.html', context)


class ClassFormView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk=None):
        lesson_class = None
        if pk:
            lesson_class = get_object_or_404(LessonClass, school=request.school, pk=pk)
        periods = LessonPeriod.objects.filter(school=request.school).order_by('-start_date')
        school_classes = SchoolClass.objects.filter(school=request.school).order_by('level', 'name')
        context = {
            'lesson_class': lesson_class,
            'is_edit': pk is not None,
            'periods': periods,
            'school_classes': school_classes,
        }
        return render(request, 'lessons/admin/class_form.html', context)

    def post(self, request, pk=None):
        school = request.school
        lesson_class = None
        if pk:
            lesson_class = get_object_or_404(LessonClass, school=school, pk=pk)

        period_id = request.POST.get('period', '')
        name = request.POST.get('name', '').strip()
        level_hint = request.POST.get('level_hint', '').strip()
        capacity = request.POST.get('capacity', '').strip()
        fee_amount = request.POST.get('fee_amount', '').strip()
        school_class_id = request.POST.get('school_class', '').strip()
        notes = request.POST.get('notes', '').strip()

        period = get_object_or_404(LessonPeriod, school=school, pk=period_id) if period_id else None
        if not period or not name:
            messages_error(request, 'Period and class name are required.')
            return redirect('lessons:class_form', pk) if pk else redirect('lessons:class_new')

        try:
            fee = Decimal(fee_amount) if fee_amount else None
        except (ValueError, ArithmeticError):
            messages_error(request, 'Invalid fee amount.')
            return redirect('lessons:class_form', pk) if pk else redirect('lessons:class_new')

        qs = LessonClass.objects.filter(school=school, period=period, name=name)
        if pk:
            qs = qs.exclude(pk=pk)
        if qs.exists():
            messages_error(request, f'A class named "{name}" already exists in this period.')
            return redirect('lessons:class_form', pk) if pk else redirect('lessons:class_new')

        school_class = None
        if school_class_id:
            try:
                school_class = SchoolClass.objects.get(school=school, pk=school_class_id)
            except SchoolClass.DoesNotExist:
                pass

        defaults = {
            'period': period,
            'name': name,
            'level_hint': level_hint,
            'capacity': int(capacity) if capacity.isdigit() else None,
            'fee_amount': fee,
            'school_class': school_class,
            'notes': notes,
        }
        if lesson_class:
            LessonClass.objects.filter(pk=lesson_class.pk).update(**defaults)
            messages_success(request, f'Class "{name}" updated.')
        else:
            LessonClass.objects.create(school=school, **defaults)
            messages_success(request, f'Class "{name}" created.')
        return redirect('lessons:class_list')


class ClassDeleteView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        lesson_class = get_object_or_404(LessonClass, school=request.school, pk=pk)
        name = str(lesson_class)
        count = lesson_class.enrollments.count()
        if count:
            messages_error(request, f'Cannot delete "{name}" — {count} enrollment(s) exist.')
            return redirect('lessons:class_list')
        lesson_class.delete()
        messages_success(request, f'Class "{name}" deleted.')
        return redirect('lessons:class_list')


class ClassTeachersView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        lesson_class = get_object_or_404(LessonClass, school=request.school, pk=pk)
        teachers = User.objects.filter(
            school=request.school, role=Roles.TEACHER, is_active=True,
        ).order_by('first_name')
        context = {'lesson_class': lesson_class, 'teachers': teachers}
        return render(request, 'lessons/admin/class_teachers.html', context)

    def post(self, request, pk):
        school = request.school
        lesson_class = get_object_or_404(LessonClass, school=school, pk=pk)
        action = request.POST.get('action')
        teacher_id = request.POST.get('teacher')
        teacher = get_object_or_404(
            User, school=school, pk=teacher_id, role=Roles.TEACHER,
        )
        if action == 'add':
            LessonTeacherAssignment.objects.get_or_create(
                school=school, lesson_class=lesson_class, teacher=teacher,
            )
            messages_success(request, f'{teacher.get_full_name()} added.')
        elif action == 'remove':
            LessonTeacherAssignment.objects.filter(
                school=school, lesson_class=lesson_class, teacher=teacher,
            ).delete()
            messages_success(request, f'{teacher.get_full_name()} removed.')
        return redirect('lessons:class_teachers', pk=lesson_class.pk)


class EnrollmentListView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        enrollments = LessonEnrollment.objects.filter(
            school=school,
        ).select_related('lesson_class', 'lesson_class__period', 'student').select_related(
            'student__user',
        )
        period_id = request.GET.get('period', '')
        class_id = request.GET.get('class', '')
        status = request.GET.get('status', '')
        q = request.GET.get('q', '').strip()
        if period_id:
            enrollments = enrollments.filter(lesson_class__period_id=period_id)
        if class_id:
            enrollments = enrollments.filter(lesson_class_id=class_id)
        if status:
            enrollments = enrollments.filter(status=status)
        if q:
            enrollments = enrollments.filter(
                Q(external_name__icontains=q)
                | Q(parent_name__icontains=q)
                | Q(parent_phones__0__icontains=q)
                | Q(student__user__first_name__icontains=q)
                | Q(student__user__last_name__icontains=q)
            )
        enrollments = enrollments.order_by('-registered_on')
        periods = LessonPeriod.objects.filter(school=school).order_by('-start_date')
        context = {
            'enrollments': enrollments,
            'periods': periods,
            'period_id': period_id,
            'class_id': class_id,
            'status': status,
            'q': q,
        }
        return render(request, 'lessons/admin/enrollment_list.html', context)


class EnrollmentFormView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk=None):
        enrollment = None
        if pk:
            enrollment = get_object_or_404(
                LessonEnrollment,
                school=request.school, pk=pk,
            )
        periods = LessonPeriod.objects.filter(school=request.school).order_by('-start_date')
        students = self._students(request)
        current_class_text = ''
        if enrollment and enrollment.lesson_class_id:
            current_class_text = enrollment.lesson_class.name
        context = {
            'enrollment': enrollment,
            'is_edit': pk is not None,
            'periods': periods,
            'students': students,
            'current_class_text': current_class_text,
        }
        return render(request, 'lessons/admin/enrollment_form.html', context)

    def post(self, request, pk=None):
        school = request.school
        enrollment = None
        if pk:
            enrollment = get_object_or_404(LessonEnrollment, school=school, pk=pk)

        lesson_class_id = request.POST.get('lesson_class', '')
        lesson_class = get_object_or_404(LessonClass, school=school, pk=lesson_class_id)
        student_id = request.POST.get('student', '')
        student = None
        if student_id:
            student = get_object_or_404(Student, school=school, pk=student_id)

        data = {
            'lesson_class': lesson_class,
            'student': student,
            'external_name': request.POST.get('external_name', '').strip(),
            'age': request.POST.get('age', '').strip() or None,
            'parent_name': request.POST.get('parent_name', '').strip(),
            'parent_phones': [
                p.strip() for p in request.POST.getlist('parent_phones')
                if p.strip()
            ],
            'emergency_contact': request.POST.get('emergency_contact', '').strip(),
            'relationship': request.POST.get('relationship', LessonEnrollment.Relationship.GUARDIAN),
            'learning_goals': request.POST.get('learning_goals', '').strip(),
            'referral_notes': request.POST.get('referral_notes', '').strip(),
            'source': request.POST.get('source', LessonEnrollment.Source.OTHER),
            'consent_given': request.POST.get('consent_given') == 'on',
            'consent_date': request.POST.get('consent_date', '').strip() or None,
            'status': request.POST.get('status', LessonEnrollment.Status.REGISTERED),
        }

        if not data['parent_name'] or not data['parent_phones']:
            messages_error(request, 'Parent name and at least one phone number are required.')
            return redirect('lessons:enrollment_form', pk) if pk else redirect('lessons:enrollment_new')
        if not data['student'] and not data['external_name']:
            messages_error(request, 'Link an existing student or provide an external child name.')
            return redirect('lessons:enrollment_form', pk) if pk else redirect('lessons:enrollment_new')

        if enrollment:
            LessonEnrollment.objects.filter(pk=enrollment.pk).update(
                lesson_class=data['lesson_class'],
                student=data['student'],
                external_name=data['external_name'],
                age=data['age'],
                parent_name=data['parent_name'],
                parent_phones=data['parent_phones'],
                emergency_contact=data['emergency_contact'],
                relationship=data['relationship'],
                learning_goals=data['learning_goals'],
                referral_notes=data['referral_notes'],
                source=data['source'],
                consent_given=data['consent_given'],
                consent_date=data['consent_date'],
                status=data['status'],
            )
            messages_success(request, f'Registration for {enrollment.child_name} updated.')
            return redirect('lessons:enrollment_detail', pk=enrollment.pk)

        enrollment = LessonEnrollment.objects.create(school=school, **data)
        messages_success(request, f'Registration recorded for {enrollment.child_name}.')
        return redirect('lessons:enrollment_detail', pk=enrollment.pk)

    def _students(self, request):
        return Student.objects.filter(
            school=request.school,
        ).select_related('user').order_by('user__last_name')


class EnrollmentDetailView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        enrollment = get_object_or_404(
            LessonEnrollment.objects.select_related(
                'lesson_class', 'lesson_class__period', 'student', 'student__user',
            ),
            school=request.school, pk=pk,
        )
        payments = enrollment.payments.select_related('recorded_by').order_by('-paid_on')
        context = {
            'enrollment': enrollment,
            'payments': payments,
            'balance': max(
                enrollment.fee_amount - enrollment.amount_paid, Decimal('0.00'),
            ),
        }
        return render(request, 'lessons/admin/enrollment_detail.html', context)


class EnrollmentPrintView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        enrollment = get_object_or_404(
            LessonEnrollment.objects.select_related(
                'lesson_class', 'lesson_class__period', 'student', 'student__user',
            ),
            school=request.school, pk=pk,
        )
        school = request.school
        context = {
            'enrollment': enrollment,
            'school': school,
            'today': timezone.localdate(),
            'balance': max(
                enrollment.fee_amount - enrollment.amount_paid, Decimal('0.00'),
            ),
        }
        return render(request, 'lessons/admin/enrollment_print.html', context)


class EnrollmentCancelView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        enrollment = get_object_or_404(LessonEnrollment, school=request.school, pk=pk)
        enrollment.status = LessonEnrollment.Status.CANCELLED
        enrollment.save()
        messages_success(request, f'Registration for {enrollment.child_name} cancelled.')
        return redirect('lessons:enrollment_detail', pk=enrollment.pk)


class EnrollmentPaymentView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        enrollment = get_object_or_404(LessonEnrollment, school=school, pk=pk)
        from fees.models import Payment

        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, ArithmeticError):
            messages_error(request, 'Invalid amount.')
            return redirect('lessons:enrollment_detail', pk=enrollment.pk)
        if amount <= 0:
            messages_error(request, 'Amount must be positive.')
            return redirect('lessons:enrollment_detail', pk=enrollment.pk)

        method = request.POST.get('method', '')
        if method not in Payment.Method.values:
            messages_error(request, 'Invalid payment method.')
            return redirect('lessons:enrollment_detail', pk=enrollment.pk)

        payment = Payment.objects.create(
            school=school,
            lesson_enrollment=enrollment,
            student=enrollment.student,
            amount=amount,
            method=method,
            reference=request.POST.get('reference', '').strip() or None,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=request.user,
            description=request.POST.get(
                'description', '',
            ).strip() or f'Summer School – {enrollment.lesson_class}',
        )

        from fees.paystack import issue_receipt
        issue_receipt(payment)

        from notifications.utils import notify
        from accounts.models import User

        student_user = User.objects.filter(pk=enrollment.student_id).first()
        if student_user and student_user.email:
            notify(
                recipient=student_user,
                channel='IN_APP',
                subject=f'Payment recorded: ₦{amount:,.2f}',
                message=f'Payment of ₦{amount:,.2f} recorded for {enrollment.child_name} ({enrollment.lesson_class}).',
                reference=f'lesson-payment:{payment.id}',
                url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
            )

        if enrollment.status == LessonEnrollment.Status.REGISTERED and enrollment.amount_paid >= enrollment.fee_amount:
            enrollment.status = LessonEnrollment.Status.PAID
            enrollment.save()

        messages_success(request, f'Payment of ₦{amount:,.2f} recorded.')
        return redirect('lessons:enrollment_detail', pk=enrollment.pk)


class EnrollmentExportView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        enrollments = LessonEnrollment.objects.filter(
            school=school,
        ).select_related('lesson_class', 'lesson_class__period', 'student').select_related(
            'student__user',
        ).order_by('-registered_on')

        period_id = request.GET.get('period', '')
        class_id = request.GET.get('class', '')
        status = request.GET.get('status', '')
        if period_id:
            enrollments = enrollments.filter(lesson_class__period_id=period_id)
        if class_id:
            enrollments = enrollments.filter(lesson_class_id=class_id)
        if status:
            enrollments = enrollments.filter(status=status)

        from core.utils import csv_response

        response, writer = csv_response(
            f'summer_school_enrollments_{timezone.now():%Y%m%d}.csv',
            header=[
                'Period', 'Class', 'Child', 'Linked Student', 'Age',
                'Current Class', 'Parent Name', 'Parent Phone', 'Relationship',
                'Source', 'Fee', 'Amount Paid', 'Payment Status', 'Status',
                'Registered On', 'Consent',
            ],
        )
        for e in enrollments:
            writer.writerow([
                e.lesson_class.period.name,
                e.lesson_class.name,
                e.child_name,
                'Yes' if e.student else 'No',
                e.age or '',
                e.lesson_class.name,
                e.parent_name,
                ', '.join(e.parent_phones or []),
                e.relationship,
                e.source,
                e.fee_amount,
                e.amount_paid,
                e.payment_status,
                e.status,
                timezone.localtime(e.registered_on).strftime('%Y-%m-%d %H:%M'),
                'Yes' if e.consent_given else 'No',
            ])
        return response


class EnrollmentRegisterStudentView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        enrollment = get_object_or_404(
            LessonEnrollment,
            school=school, pk=pk,
        )
        if enrollment.student:
            messages_error(request, 'This participant is already linked to a student.')
            return redirect('lessons:enrollment_detail', pk=enrollment.pk)

        external_name = enrollment.external_name or ''
        first_name, middle_name, last_name = parse_full_name(external_name)

        estimated_dob = ''
        if enrollment.age:
            from datetime import date
            today = date.today()
            estimated_dob = date(today.year - enrollment.age, today.month, today.day).isoformat()

        parent_phones = enrollment.parent_phones or []
        parent_phone = parent_phones[0] if parent_phones else ''

        context = {
            'enrollment': enrollment,
            'first_name': first_name,
            'middle_name': middle_name,
            'last_name': last_name,
            'new_email': '',
            'new_phone_number': parent_phone,
            'date_of_birth': estimated_dob,
            'admission_date': timezone.localdate().isoformat(),
            'guardian_0_name': enrollment.parent_name,
            'guardian_0_phone': parent_phone,
            'guardian_0_relationship': enrollment.relationship,
            'classes': SchoolClass.objects.filter(school=school, is_active=True),
            'sessions': AcademicSession.objects.filter(school=school),
        }
        return render(request, 'lessons/admin/enrollment_register_student.html', context)

    def post(self, request, pk):
        school = request.school
        enrollment = get_object_or_404(
            LessonEnrollment,
            school=school, pk=pk,
        )
        if enrollment.student:
            messages_error(request, 'This participant is already linked to a student.')
            return redirect('lessons:enrollment_detail', pk=enrollment.pk)

        first_name = request.POST.get('first_name', '').strip()
        middle_name = request.POST.get('middle_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('new_email', '').strip()
        phone_number = request.POST.get('new_phone_number', '').strip()
        date_of_birth = request.POST.get('date_of_birth', '').strip()
        gender = request.POST.get('gender', '').strip()
        admission_date = request.POST.get('admission_date', '').strip()
        status = request.POST.get('status', 'ACTIVE')
        class_id = request.POST.get('class_id', '').strip()
        session_id = request.POST.get('session_id', '').strip()

        if not all([first_name, last_name, date_of_birth, gender, admission_date]):
            messages_error(request, 'Name, date of birth, gender, and admission date are required.')
            return redirect('lessons:enrollment_register_student', pk=enrollment.pk)

        try:
            with transaction.atomic():
                username_input = generate_username(first_name, last_name)
                base_username = username_input
                counter = 1
                while User.objects.filter(username=username_input).exists():
                    username_input = f"{base_username}{counter}"
                    counter += 1

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

                from django.utils.dateparse import parse_date
                school_class = None
                if class_id:
                    school_class = SchoolClass.objects.filter(
                        school=school, pk=class_id
                    ).first()

                admission_number = generate_admission_number(school, school_class)

                student = Student(
                    school=school,
                    user=user,
                    admission_number=admission_number,
                    date_of_birth=parse_date(date_of_birth),
                    gender=gender,
                    admission_date=parse_date(admission_date),
                    status=status,
                )
                student.full_clean()
                student.save()

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

                guardian_index = 0
                while True:
                    g_name = request.POST.get(f'guardian_{guardian_index}_name', '').strip()
                    g_email = request.POST.get(f'guardian_{guardian_index}_email', '').strip()
                    g_phone = request.POST.get(f'guardian_{guardian_index}_phone', '').strip()
                    g_relationship = request.POST.get(f'guardian_{guardian_index}_relationship', 'GUARDIAN')

                    if not g_name and not g_email and not g_phone:
                        break

                    if g_name:
                        parent_user = find_or_create_parent(
                            school, g_name, email=g_email, phone=g_phone, relationship=g_relationship
                        )
                        StudentGuardianLink.objects.create(
                            school=school,
                            student=student,
                            guardian=parent_user,
                            relationship=g_relationship,
                            is_primary_contact=(guardian_index == 0),
                        )

                    guardian_index += 1

                enrollment.student = student
                enrollment.external_name = ''
                enrollment.age = None
                enrollment.current_class_text = ''
                enrollment.save(update_fields=['student', 'external_name', 'age', 'current_class_text'])

                from notifications.utils import notify_admins
                notify_admins(
                    school=school,
                    subject=f'Student registered from extra lesson: {student}',
                    message=(
                        f'{student} ({admission_number}) was registered from extra lesson enrollment for {enrollment.lesson_class}.'
                    ),
                    reference=f'lesson-register:{student.pk}',
                    url=reverse('school_admin:student_detail', kwargs={'pk': student.pk}),
                )

                messages_success(
                    request,
                    f'Student "{user.get_full_name()}" registered successfully from extra lesson.',
                )
                return redirect('school_admin:student_detail', pk=student.pk)

        except Exception as e:
            messages_error(request, f'Error registering student: {e}')
            return redirect('lessons:enrollment_register_student', pk=enrollment.pk)