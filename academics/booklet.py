"""Shared result-booklet context builder.

Used by the inline booklet views (student + parent portals) and the PDF
renderer so the score/grade data is assembled exactly once.
"""
from students.models import ClassEnrollment


def build_booklet_context(student, term, school):
    """Build the context dict for a student result booklet.

    Returns ``(context, enrollment)``, or ``(None, None)`` when the student
    has no enrollment in the term's session.
    """
    from .models import Score, GradeScale, TermResult

    enrollment = ClassEnrollment.objects.filter(
        student=student, session=term.session
    ).select_related('school_class').first()

    if not enrollment:
        return None, None

    scores = Score.objects.filter(
        student=student, term=term
    ).select_related('subject').order_by('subject__name')

    term_result = TermResult.objects.filter(
        student=student, term=term
    ).first()

    grade_scale = GradeScale.objects.filter(school=school).order_by('-min_score')

    score_data = []
    for score in scores:
        grade_label = GradeScale.get_grade(school, score.total_score)
        grade_obj = (
            GradeScale.objects.filter(school=school, label=grade_label).first()
            if grade_label else None
        )
        score_data.append({
            'subject': score.subject.name,
            'test_1': score.test_1 or 0,
            'test_2': score.test_2 or 0,
            'test_3': score.test_3 or 0,
            'exam': score.exam_score or 0,
            'total': score.total_score,
            'grade': grade_label or '-',
            'position': score.position,
            'remark': grade_obj.remark if grade_obj else '-',
        })

    class_size = ClassEnrollment.objects.filter(
        school_class=enrollment.school_class, session=term.session, is_current=True
    ).count()

    context = {
        'school': school,
        'student': student,
        'term': term,
        'enrollment': enrollment,
        'school_class': enrollment.school_class,
        'scores': score_data,
        'term_result': term_result,
        'grade_scale': grade_scale,
        'class_size': class_size,
    }
    return context, enrollment
