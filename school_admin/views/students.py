"""Student management views for school admin portal."""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction, IntegrityError

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from students.models import Student, ClassEnrollment, StudentGuardianLink
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

        from students.models import SchoolClass
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
        }
        return render(request, 'school_admin/student_detail.html', context)


class StudentCreateView(RoleRequiredMixin, View):
    """Create a new student (simplified — shows a form)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        from students.models import SchoolClass
        from accounts.models import User
        school = request.school
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        # Show users with STUDENT role for selection
        users = User.objects.filter(school=school, role=Roles.STUDENT, is_active=True)
        context = {
            'classes': classes,
            'users': users,
        }
        return render(request, 'school_admin/student_create.html', context)

    def post(self, request):
        # Delegate to the actual creation logic
        messages.info(request, 'Use the full student creation form in the admin panel for complete data entry.')
        return redirect('school_admin:student_list')


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
