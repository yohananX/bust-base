"""Parent/guardian views for school admin portal.

Parents are not created from this page — accounts come from student
imports or the guardian linking on the student detail page. This is a
read-only overview with search.
"""
from django.db.models import Q
from django.shortcuts import render
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User


class ParentListView(RoleRequiredMixin, View):
    """List all parents/guardians with search by name, email or username."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        parents = User.objects.filter(
            school=school,
            role=Roles.PARENT,
        ).prefetch_related(
            'student_links__student__user',
            'student_links__student__enrollments__school_class',
        )

        q = request.GET.get('q', '').strip()
        if q:
            parents = parents.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(username__icontains=q)
            )

        parents = parents.order_by('last_name', 'first_name')

        rows = []
        for parent in parents:
            links = list(parent.student_links.all())
            links.sort(key=lambda link: (
                link.student.user.last_name or '',
                link.student.user.first_name or '',
            ))
            children = []
            for link in links:
                student = link.student
                enrollment = next(
                    (e for e in student.enrollments.all() if e.is_current), None
                )
                children.append({
                    'student': student,
                    'class_name': (
                        enrollment.school_class.name if enrollment else None
                    ),
                })
            rows.append({
                'parent': parent,
                'children': children,
            })

        return render(request, 'school_admin/parent_list.html', {
            'rows': rows,
            'q': q,
        })
