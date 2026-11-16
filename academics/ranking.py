from .models import Score


def _assign_dense_ranks(items, score_attr, id_attr=None, *, key=None):
    """Assign dense/ Olympic ranks to items based on a numeric score attribute.

    ``items`` may be a list of objects or dicts. When ``key`` is given, it is
    used as the sort key; otherwise items are sorted by
    ``(-score_attr, id_attr)``.

    Returns a list of (item, rank) tuples in ranked order.
    """
    def _score(item):
        if isinstance(item, dict):
            return item[score_attr]
        return getattr(item, score_attr)

    if key is None:
        def key(x):
            if id_attr is None:
                return (-_score(x), 0)
            if isinstance(x, dict):
                return (-_score(x), x[id_attr])
            return (-_score(x), getattr(x, id_attr))

    items_sorted = sorted(items, key=key)
    ranked = []
    prev_score = None
    rank = 0
    for i, item in enumerate(items_sorted, start=1):
        score = _score(item)
        if score != prev_score:
            rank = i
        ranked.append((item, rank))
        prev_score = score
    return ranked


def compute_positions(class_subject, term):
    """Compute ranking for one offering-specific subject and term.

    Olympic/dense ranking means:
      - Students with the same total_score share the same position.
      - The next lower total_score gets position = (1-based index of first occurrence),
        not previous_position + 1.
      - Example: scores [90, 85, 85, 70] -> positions [1, 2, 2, 4]
      - Example: scores [90, 90, 85]     -> positions [1, 1, 3]
      - Example: scores [70]             -> positions [1]

    Incomplete scores (any component is None or missing) get position=None
    and are excluded from ranking. Scores that have not been approved by
    moderation (PENDING/REJECTED) also get position=None — ranking only
    reflects scores that made it onto the official record, so rejected
    scores can never skew positions.

    The subject configuration owns the exact ClassOffering, so historical
    terms can never drift onto another session's class roster.

    Returns the number of scores that received a position.
    """
    if class_subject.class_offering.academic_session_id != term.session_id:
        raise ValueError(
            'ClassSubject offering session must match the ranking term session.'
        )

    base = Score.objects.filter(
        class_subject=class_subject,
        term=term,
        student__enrollments__class_offering=class_subject.class_offering,
    ).select_related('student')

    # Reset all positions to None first
    base.update(position=None)

    # Fetch only complete, APPROVED scores into Python for sorting by
    # total_score (total_score is a Python property, not a database column)
    complete = [
        s for s in base if s.is_complete
        and s.moderation_status == Score.MODERATION_APPROVED
    ]

    # Sort by total_score descending, then student_id for deterministic tie-breaking
    complete.sort(key=lambda s: (-s.total_score, s.student_id))

    # Olympic/dense ranking: [90, 85, 85, 70] -> [1, 2, 2, 4]
    for score, rank in _assign_dense_ranks(complete, 'total_score', 'student_id'):
        score.position = rank
        score.save(update_fields=['position'])

    return len(complete)


def compute_term_summary(class_offering, term):
    """Compute TermResult rows for every student in an offering and term.

    Creates/updates TermResult with:
    - grand_total: sum of all Score.total_score for this student this term
    - average: grand_total / number_of_subjects
    - overall_position: Olympic/dense ranking by grand_total (reuses same logic as compute_positions)
    - total_subjects: count of subjects with complete scores

    Only scores that have been APPROVED by moderation count — pending or
    rejected scores never leak into the official term record.

    Does NOT touch attendance, affective ratings, or remarks — those are manual.
    Returns the number of TermResult rows created/updated.
    """
    from students.models import Student
    from .models import Score, TermResult

    if class_offering.academic_session_id != term.session_id:
        raise ValueError(
            'ClassOffering session must match the term summary session.'
        )

    # Get all students enrolled in this exact class offering.
    enrolled_students = Student.objects.filter(
        school=class_offering.school,
        enrollments__class_offering=class_offering,
    ).distinct()

    # Collect totals per student
    student_totals = []
    for student in enrolled_students:
        scores = Score.objects.filter(
            student=student,
            term=term,
            moderation_status=Score.MODERATION_APPROVED,
            class_subject__class_offering=class_offering,
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
    def _summary_key(entry):
        student = entry['student']
        return (-entry['grand_total'], student.pk)

    for entry, rank in _assign_dense_ranks(student_totals, 'grand_total', key=_summary_key):
        entry['overall_position'] = rank

    # Create/update TermResult rows
    count = 0
    for entry in student_totals:
        TermResult.objects.update_or_create(
            school=class_offering.school,
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

    # Drop stale TermResult rows for enrolled students who no longer have
    # any approved complete scores (e.g. all their scores were rejected).
    # Without this, a rejected student's old aggregates would keep showing
    # on booklets.
    enrolled_ids = set(enrolled_students.values_list('pk', flat=True))
    kept_ids = {entry['student'].pk for entry in student_totals}
    TermResult.objects.filter(
        school=class_offering.school,
        term=term,
        student__in=enrolled_ids,
    ).exclude(student_id__in=kept_ids).delete()

    return count
