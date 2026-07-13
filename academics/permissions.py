from django.db import DatabaseError


def teacher_can_access(teacher, subject, school_class, session):
    """Check if a teacher has a TeacherAssignment for the given subject, class, and session.

    Returns True if an assignment exists, False otherwise.
    Handles potential database errors gracefully by returning False on exception.
    """
    try:
        from .models import TeacherAssignment

        return TeacherAssignment.objects.filter(
            teacher=teacher,
            subject=subject,
            school_class=school_class,
            session=session,
        ).exists()
    except DatabaseError:
        return False
