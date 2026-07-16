"""PDF generation for result booklets."""
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML


def render_result_booklet_pdf(student, term):
    """Render a result booklet PDF for a student in a given term.

    Returns an HttpResponse with PDF content, or None if no enrollment found.
    """
    from .models import Score, GradeScale, TermResult
    from students.models import ClassEnrollment

    school = student.school

    # Get current enrollment for this term
    enrollment = ClassEnrollment.objects.filter(
        student=student, session=term.session
    ).select_related('school_class').first()

    if not enrollment:
        return None

    school_class = enrollment.school_class

    # Get scores for this student this term
    scores = Score.objects.filter(
        student=student, term=term
    ).select_related('subject').order_by('subject__name')

    # Get term result (aggregate)
    term_result = TermResult.objects.filter(
        student=student, term=term
    ).first()

    # Get grade for each score
    score_data = []
    for score in scores:
        grade_label = GradeScale.get_grade(school, score.total_score)
        grade_obj = GradeScale.objects.filter(
            school=school, label=grade_label
        ).first() if grade_label else None
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

    # Get grade scale legend
    grade_scale = GradeScale.objects.filter(school=school).order_by('-min_score')

    # Count students in class for position display
    class_size = ClassEnrollment.objects.filter(
        school_class=school_class, session=term.session, is_current=True
    ).count()

    # Get school logo URL if available
    logo_url = ''
    if school.logo:
        logo_url = school.logo.url

    context = {
        'school': school,
        'student': student,
        'enrollment': enrollment,
        'school_class': school_class,
        'term': term,
        'scores': score_data,
        'term_result': term_result,
        'grade_scale': grade_scale,
        'class_size': class_size,
        'logo_url': logo_url,
    }

    html_string = render_to_string('academics/result_booklet.html', context)
    pdf_bytes = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"result_{student.admission_number}_{term.name}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
