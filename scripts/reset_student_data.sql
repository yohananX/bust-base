-- =============================================================================
-- Selective Student Data Reset (SQLite)
-- =============================================================================
-- This script deletes ALL student-related records for EVERY school while
-- preserving:
--   - core_school
--   - students_schoolclass
--   - academics_subject
--   - core_academicsession
--   - core_term
--   - academics_teacherassignment
--   - fees_feestructure, fees_feecategory
--   - payroll_* (grades, runs, disbursements, etc.)
--   - finance_* (projects, expenditures, categories)
--   - lessons_lessonperiod, lessons_lessonclass, lessons_lessonteacherassignment
--
-- IMPORTANT: Because Student.user is CASCADE and User is referenced by
-- Payment.recorded_by, Score.entered_by, etc. with CASCADE, deleting a
-- Student may cascade-delete records that student created for OTHER students.
-- For a full-school reset this is acceptable.
--
-- Run inside a transaction so you can ROLLBACK if needed:
--   BEGIN;
--   ... paste statements here ...
--   COMMIT;  -- or ROLLBACK;
-- =============================================================================

-- 1. Notifications sent to student/parent users
DELETE FROM notifications_notificationlog
WHERE recipient_id IN (
    SELECT u.user_ptr_id
    FROM students_student s
    JOIN accounts_user u ON u.id = s.user_id
    UNION
    SELECT guardian_id
    FROM students_studentguardianlink
);

-- 2. Scores entered for students
DELETE FROM academics_score
WHERE student_id IN (SELECT id FROM students_student);

-- 3. Term results
DELETE FROM academics_termresult
WHERE student_id IN (SELECT id FROM students_student);

-- 4. Lesson enrollments (student FK is SET_NULL, so delete explicitly)
DELETE FROM lessons_lessonenrollment
WHERE student_id IN (SELECT id FROM students_student);

-- 5. Payments where student is the payer (covers invoice-less payments)
DELETE FROM fees_payment
WHERE student_id IN (SELECT id FROM students_student);

-- 6. Invoices (cascades to InvoiceLineItem and FeeReceipt via CASCADE)
DELETE FROM fees_invoice
WHERE student_id IN (SELECT id FROM students_student);

-- 7. Class enrollments
DELETE FROM students_classenrollment
WHERE student_id IN (SELECT id FROM students_student);

-- 8. Guardian links
DELETE FROM students_studentguardianlink
WHERE student_id IN (SELECT id FROM students_student);

-- 9. Students (cascades to User, which cascades to any remaining records
--     created by that user such as Payment.recorded_by, Score.entered_by)
DELETE FROM students_student;

-- 10. Orphaned test artifacts (no student, no invoice, no lesson)
DELETE FROM fees_payment
WHERE student_id IS NULL AND invoice_id IS NULL;

DELETE FROM lessons_lessonenrollment
WHERE student_id IS NULL;

-- =============================================================================
-- Verification queries (run after COMMIT)
-- =============================================================================
-- SELECT COUNT(*) FROM students_student;          -- expect 0
-- SELECT COUNT(*) FROM fees_invoice;               -- expect 0
-- SELECT COUNT(*) FROM fees_payment;               -- expect 0
-- SELECT COUNT(*) FROM academics_score;            -- expect 0
-- SELECT COUNT(*) FROM students_schoolclass;       -- expect > 0
-- SELECT COUNT(*) FROM academics_subject;          -- expect > 0
-- SELECT COUNT(*) FROM core_school;                -- expect > 0
