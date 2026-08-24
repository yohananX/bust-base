"""Populate the entire school from seed data.

Pipeline (in order):
1. Wipe existing students/staff/subjects/classes/fees for the school.
2. Import classes, subjects and staff through the real data_import importers.
3. Create fee categories + structures for all 3 terms (auto-invoicing uses them).
4. Build TeacherAssignment rows for the current session.
5. Import 400 students through the real StudentImporter (enrollment + auto invoices).
6. Simulate payments (fully paid / partial / pending transfer / unpaid).
7. Generate scores, moderation, positions and term results for the current term.
"""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school.settings')

import django

django.setup()

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import Roles, User
from academics.models import Score, Subject, TeacherAssignment, TermResult
from academics.ranking import compute_positions, compute_term_summary
from core.models import AcademicSession, Term
from data_import.importers import (
    ClassImporter, StaffImporter, StudentImporter, SubjectImporter,
)
from fees.models import FeeCategory, FeeReceipt, FeeStructure, Invoice, InvoiceLineItem, Payment
from students.models import ClassEnrollment, SchoolClass, Student, StudentGuardianLink

from curriculum import CLASSES, CURRICULUM, FEE_TIERS, PRIMARY_SUBJECTS, TEACHERS

HERE = os.path.dirname(os.path.abspath(__file__))
RNG = random.Random(2026)


def get_school():
    admin = User.objects.filter(role=Roles.ADMIN, school__isnull=False) \
        .exclude(is_superuser=True).first()
    if admin is None:
        raise SystemExit('No school admin user found.')
    return admin.school


def wipe(school):
    print('--- wiping old data ---')
    counts = {}
    models = [
        TeacherAssignment, Score, TermResult, Payment, FeeReceipt,
        InvoiceLineItem, Invoice, FeeStructure, FeeCategory,
        StudentGuardianLink, ClassEnrollment, Student, Subject, SchoolClass,
    ]
    for model in models:
        qs = model.objects.filter(school=school) if hasattr(model, 'school') else model.objects.all()
        counts[model.__name__] = qs.count()
        qs.delete()
    n_users = User.objects.filter(
        school=school, role__in=[Roles.STUDENT, Roles.TEACHER, Roles.PARENT],
    ).count()
    User.objects.filter(
        school=school, role__in=[Roles.STUDENT, Roles.TEACHER, Roles.PARENT],
    ).delete()
    print('  deleted:', counts)
    print('  deleted users:', n_users)


def import_classes_and_subjects(school):
    print('--- importing classes ---')
    result = ClassImporter(school=school, dry_run=False, verbose=False) \
        .import_csv(os.path.join(HERE, 'classes.csv'))
    print('  classes:', result)
    print('--- importing subjects ---')
    result = SubjectImporter(school=school, dry_run=False, verbose=False) \
        .import_csv(os.path.join(HERE, 'subjects.csv'))
    print('  subjects:', result)


def create_fee_structures(school, session):
    print('--- fee structures ---')
    terms = list(Term.objects.filter(school=school, session=session).order_by('start_date'))
    if len(terms) != 3:
        raise SystemExit('Expected 3 terms for the session, got {}'.format(len(terms)))
    classes = {c.name: c for c in SchoolClass.objects.filter(school=school)}
    created = 0
    for class_name in CLASSES:
        category, _ = FeeCategory.objects.get_or_create(
            school=school, name='{} School Fees'.format(class_name),
            defaults={'is_compulsory': True},
        )
        for term in terms:
            FeeStructure.objects.create(
                school=school, school_class=classes[class_name],
                term=term, category=category, amount=Decimal(FEE_TIERS[class_name]),
            )
            created += 1
    print('  structures created:', created)


def import_staff(school):
    print('--- importing staff ---')
    result = StaffImporter(school=school, dry_run=False, verbose=False) \
        .import_csv(os.path.join(HERE, 'staff.csv'))
    print('  staff:', result)


def build_assignments(school, session):
    print('--- teacher assignments ---')
    classes = {c.name: c for c in SchoolClass.objects.filter(school=school)}
    subjects = {s.name: s for s in Subject.objects.filter(school=school)}
    users = {u.username: u for u in User.objects.filter(school=school, role=Roles.TEACHER)}
    created = 0
    for first, last, spec in TEACHERS:
        user = users.get('{}.{}'.format(first, last).lower().replace("'", '').replace('-', ''))
        if user is None:
            candidates = [u for u in users.values() if u.first_name == first and u.last_name == last]
            user = candidates[0] if candidates else None
        if user is None:
            raise SystemExit('Teacher not found: {} {}'.format(first, last))
        pairs = []
        if isinstance(spec, str):
            pairs = [(subject, spec) for subject in PRIMARY_SUBJECTS]
        else:
            pairs = spec
        for subject_name, class_name in pairs:
            TeacherAssignment.objects.create(
                school=school, teacher=user, subject=subjects[subject_name],
                school_class=classes[class_name], session=session,
            )
            created += 1
    print('  assignments created:', created)
    return classes, subjects


def import_students(school):
    print('--- importing students ---')
    result = StudentImporter(school=school, dry_run=False, verbose=False) \
        .import_csv(os.path.join(HERE, 'students.csv'))
    print('  students:', result)


def simulate_payments(school, term):
    print('--- simulating payments ---')
    invoices = list(Invoice.objects.filter(school=school, term=term).select_related('student'))
    admin = User.objects.filter(school=school, role=Roles.ADMIN) \
        .exclude(is_superuser=True).first()
    methods = [Payment.Method.CASH, Payment.Method.POS, Payment.Method.BANK_TRANSFER,
               Payment.Method.CARD]
    weights = [0.25, 0.25, 0.30, 0.20]
    start = term.start_date + timedelta(days=4)
    end = term.end_date - timedelta(days=10)
    created = {'full': 0, 'partial': 0, 'pending': 0}
    for invoice in invoices:
        roll = RNG.random()
        if roll < 0.55:
            amount = invoice.total_amount
            status = Payment.Status.CONFIRMED
            created['full'] += 1
        elif roll < 0.75:
            amount = (invoice.total_amount * Decimal(str(RNG.uniform(0.5, 0.75))))
            amount = amount.quantize(Decimal('0.01'))
            status = Payment.Status.CONFIRMED
            created['partial'] += 1
        elif roll < 0.85:
            amount = invoice.total_amount
            status = Payment.Status.PENDING
            created['pending'] += 1
        else:
            continue
        method = RNG.choices(methods, weights=weights)[0]
        paid_on = timezone.make_aware(start + (end - start) * RNG.random())
        Payment.objects.create(
            school=school, invoice=invoice, student=invoice.student,
            description='School fees - {}'.format(term.name),
            amount=amount, method=method, status=status,
            reference='PAY-{:08d}'.format(RNG.randint(0, 99999999)),
            paid_on=paid_on, recorded_by=admin,
            paid_by_name='{} {}'.format(invoice.student.user.first_name,
                                        invoice.student.user.last_name),
            paid_by_relation='Student',
        )
    print('  payments:', created)


def generate_scores(school, term, classes, subjects):
    print('--- generating scores ---')
    admin = User.objects.filter(school=school, role=Roles.ADMIN) \
        .exclude(is_superuser=True).first()
    assignments = {}
    for a in TeacherAssignment.objects.filter(school=school, session=term.session):
        assignments[(a.school_class_id, a.subject_id)] = a.teacher_id

    students = list(Student.objects.filter(school=school).select_related('user'))
    enrollments = {
        e.student_id: e for e in ClassEnrollment.objects.filter(
            school=school, session=term.session, is_current=True,
        )
    }
    created = {'scores': 0, 'approved': 0, 'pending': 0}
    for student in students:
        enrollment = enrollments.get(student.id)
        if enrollment is None:
            continue
        for subject_name in CURRICULUM[enrollment.school_class.name]:
            subject = subjects[subject_name]
            teacher_id = assignments.get((enrollment.school_class_id, subject.id))
            approved = RNG.random() < 0.85
            score = Score.objects.create(
                school=school, student=student, subject=subject, term=term,
                test_1=RNG.randint(4, 10), test_2=RNG.randint(4, 10),
                test_3=RNG.randint(4, 10), exam_score=RNG.randint(25, 68),
                entered_by_id=teacher_id or admin.id,
                moderation_status=(Score.MODERATION_APPROVED if approved
                                   else Score.MODERATION_PENDING),
                moderated_by=admin if approved else None,
                moderated_at=timezone.now() if approved else None,
            )
            created['scores'] += 1
            created['approved' if approved else 'pending'] += 1
    print('  scores:', created)
    return assignments


def compute_rankings(school, term, classes, subjects):
    print('--- computing rankings ---')
    positioned = 0
    for class_name, class_obj in classes.items():
        for subject_name in CURRICULUM[class_name]:
            positioned += compute_positions(class_obj, subjects[subject_name], term)
    print('  score positions:', positioned)

    summaries = 0
    for class_obj in classes.values():
        summaries += compute_term_summary(class_obj, term)
    print('  term results created/updated:', summaries)

    for result in TermResult.objects.filter(school=school, term=term):
        result.days_present = RNG.randint(48, 62)
        result.days_absent = RNG.randint(0, 6)
        result.total_days = 63
        result.punctuality = RNG.randint(3, 5)
        result.neatness = RNG.randint(3, 5)
        result.honesty = RNG.randint(3, 5)
        result.attentiveness = RNG.randint(3, 5)
        result.class_teacher_remark = RNG.choice([
            'A very good term. Keep it up.', 'Shows great promise in class.',
            'Needs to participate more in class.', 'Excellent performance this term.',
            'Consistent and hardworking.', 'A pleasure to teach.',
        ])
        result.principal_remark = RNG.choice([
            'Keep up the good work.', 'Well done, keep striving.',
            'An encouraging performance.', 'Continue to aim higher.',
        ])
        result.save()
    print('  affective/attendance updated:', TermResult.objects.filter(school=school, term=term).count())


def verify(school, term):
    print('--- verification ---')
    from django.db.models import Count, Sum
    by_role = {}
    for row in User.objects.filter(school=school).values('role') \
            .annotate(total=Count('id')):
        by_role[row['role']] = row['total']
    print('  users by role:', by_role)
    print('  classes:', SchoolClass.objects.filter(school=school).count())
    print('  subjects:', Subject.objects.filter(school=school).count())
    print('  assignments:', TeacherAssignment.objects.filter(school=school, session=term.session).count())
    print('  students:', Student.objects.filter(school=school).count())
    print('  enrollments:', ClassEnrollment.objects.filter(school=school, session=term.session).count())
    print('  invoices:', Invoice.objects.filter(school=school, term=term).count())
    paid = Payment.objects.filter(school=school, status=Payment.Status.CONFIRMED).count()
    pending = Payment.objects.filter(school=school, status=Payment.Status.PENDING).count()
    print('  confirmed payments:', paid, '| pending payments:', pending)
    print('  scores:', Score.objects.filter(school=school, term=term).count())
    print('  pending moderation:', Score.objects.filter(school=school, term=term,
                                                        moderation_status=Score.MODERATION_PENDING).count())
    print('  term results:', TermResult.objects.filter(school=school, term=term).count())
    invoices = Invoice.objects.filter(school=school, term=term)
    total_due = invoices.aggregate(t=Sum('total_amount'))['t'] or 0
    collected = Payment.objects.filter(
        school=school, status=Payment.Status.CONFIRMED,
        invoice__term=term,
    ).aggregate(t=Sum('amount'))['t'] or 0
    print('  total billed: NGN{:,.2f} | collected: NGN{:,.2f}'.format(total_due, collected))
    sample = list(invoices[:5])
    for inv in sample:
        print('    {} {} -> NGN{:,.2f} (paid NGN{:,.2f}, balance NGN{:,.2f}, {})'.format(
            inv.student.user.first_name, inv.student.user.last_name,
            inv.total_amount, inv.amount_paid, inv.balance, inv.status))


def main():
    school = get_school()
    print('School:', school.name)
    session = AcademicSession.objects.get(school=school, is_current=True)
    term = Term.objects.get(school=school, is_current=True)
    print('Session:', session.name, '| current term:', term.name)

    wipe(school)
    with transaction.atomic():
        import_classes_and_subjects(school)
        create_fee_structures(school, session)
        import_staff(school)
        classes, subjects = build_assignments(school, session)
        import_students(school)
    simulate_payments(school, term)
    generate_scores(school, term, classes, subjects)
    compute_rankings(school, term, classes, subjects)
    verify(school, term)
    print('DONE')


if __name__ == '__main__':
    main()