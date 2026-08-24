"""Read-only teacher views for the Extra Lessons / Summer School module."""
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles

from .models import LessonClass


class TeacherClassListView(RoleRequiredMixin, View):
    allowed_roles = [Roles.TEACHER]

    def get(self, request):
        school = request.school
        classes = (
            LessonClass.objects
            .filter(school=school, teacher_assignments__teacher=request.user)
            .select_related('period')
            .distinct()
            .annotate(
                enrolled_count=Count(
                    'enrollments',
                    filter=~Q(enrollments__status='CANCELLED'),
                ),
            )
            .order_by('-period__start_date', 'name')
        )
        context = {'classes': classes}
        return render(request, 'lessons/teacher/class_list.html', context)


class TeacherClassDetailView(RoleRequiredMixin, View):
    allowed_roles = [Roles.TEACHER]

    def get(self, request, pk):
        school = request.school
        lesson_class = get_object_or_404(
            LessonClass,
            school=school, pk=pk,
            teacher_assignments__teacher=request.user,
        )
        enrollments = lesson_class.enrollments.exclude(
            status='CANCELLED',
        ).select_related('student', 'student__user').order_by('-registered_on')
        context = {
            'lesson_class': lesson_class,
            'enrollments': enrollments,
        }
        return render(request, 'lessons/teacher/class_detail.html', context)