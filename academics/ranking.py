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
