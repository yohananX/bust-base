from .models import Score


def compute_positions(school_class, subject, term):
    """Compute Olympic/dense ranking for scores in a given class, subject, and term.

    Olympic/dense ranking means:
      - Students with the same total_score share the same position.
      - The next lower total_score gets position = (1-based index of first occurrence),
        not previous_position + 1.
      - Example: scores [90, 85, 85, 70] -> positions [1, 2, 2, 4]
      - Example: scores [90, 90, 85]     -> positions [1, 1, 3]
      - Example: scores [70]             -> positions [1]

    Incomplete scores (any component is None or missing) get position=None
    and are excluded from ranking.

    Returns the number of scores that received a position.
    """
    scores = Score.objects.filter(
        subject=subject,
        term=term,
        student__enrollments__school_class=school_class,
        student__enrollments__is_current=True,
    ).select_related('student')

    # Reset all positions to None first
    scores.update(position=None)

    # Fetch only complete scores into Python for sorting by total_score
    # (total_score is a Python property, not a database column)
    complete = [s for s in scores if s.is_complete]

    # Sort by total_score descending, then student_id for deterministic tie-breaking
    complete.sort(key=lambda s: (-s.total_score, s.student_id))

    # Olympic/dense ranking: [90, 85, 85, 70] -> [1, 2, 2, 4]
    rank = 0
    prev_total = None
    for i, score in enumerate(complete, start=1):
        if score.total_score != prev_total:
            rank = i
        score.position = rank
        score.save(update_fields=['position'])
        prev_total = score.total_score

    return len(complete)


def compute_term_summary(school_class, term):
    """Compute TermResult rows for every student in a class for a given term.

    Creates/updates TermResult with:
    - grand_total: sum of all Score.total_score for this student this term
    - average: grand_total / number_of_subjects
    - overall_position: Olympic/dense ranking by grand_total (reuses same logic as compute_positions)
    - total_subjects: count of subjects with complete scores

    Does NOT touch attendance, affective ratings, or remarks — those are manual.
    Returns the number of TermResult rows created/updated.
    """
    from students.models import Student
    from .models import Score, TermResult

    # Get all students currently enrolled in this class
    enrolled_students = Student.objects.filter(
        school=school_class.school,
        enrollments__school_class=school_class,
        enrollments__is_current=True,
    ).distinct()

    # Collect totals per student
    student_totals = []
    for student in enrolled_students:
        scores = Score.objects.filter(
            student=student,
            term=term,
            student__enrollments__school_class=school_class,
            student__enrollments__is_current=True,
        )
        complete_scores = [s for s in scores if s.is_complete]
        if not complete_scores:
            continue
        grand_total = sum(s.total_score for s in complete_scores)
        total_subjects = len(complete_scores)
        average = grand_total / total_subjects
        student_totals.append({
            'student': student,
            'grand_total': grand_total,
            'average': average,
            'total_subjects': total_subjects,
        })

    # Olympic/dense ranking by grand_total (same algorithm as compute_positions)
    student_totals.sort(key=lambda x: (-x['grand_total'], x['student'].pk))
    rank = 0
    prev_total = None
    for i, entry in enumerate(student_totals, start=1):
        if entry['grand_total'] != prev_total:
            rank = i
        entry['overall_position'] = rank
        prev_total = entry['grand_total']

    # Create/update TermResult rows
    count = 0
    for entry in student_totals:
        TermResult.objects.update_or_create(
            school=school_class.school,
            student=entry['student'],
            term=term,
            defaults={
                'grand_total': entry['grand_total'],
                'average': round(entry['average'], 2),
                'overall_position': entry['overall_position'],
                'total_subjects': entry['total_subjects'],
            },
        )
        count += 1

    return count
