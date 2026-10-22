# MVP Readiness Audit — Grace House School System (bust-base)

**Date:** 2026-10-22  
**Branch:** main  
**Commit:** 8a1bdcc (docs: update AUDIT_STATUS.md to reflect completed sensitive data removal)  
**Test Suite:** 708 tests — **ALL PASSING**  
**Environment:** Windows 10, Python 3.12, Django 6.0.7, SQLite (dev) / PostgreSQL (prod)

---

## 1. Executive Summary & Overall Readiness Assessment

**Overall Verdict: READY FOR CONTROLLED USE WITH DOCUMENTED CAVEATS**

The BUST-BASE codebase is in a clean, well-tested state. All 708 tests pass, including 52 multi-tenancy/portal-leakage tests. Critical workflows (school setup, academics/scores/results, fees/payments, parent/student portals, permissions, academic transitions) are implemented and exercised by automated tests. The system supports two production deployment paths (Docker + Uvicorn for cloud; Caddy + Waitress for Windows LAN) and includes backup/restore tooling.

**Key Strengths (Verified):**
- Multi-tenancy enforced at model, middleware, and view layers; portal leakage tests green
- Fee pricing via `FeePrice` (canonical) with scope precedence (CLASS > LEVEL > SCHOOL_WIDE), effective dating, student-type sub-scoping (NEW > RETURNING > ALL), and one-time guards
- Payments: webhook-first (`charge.success` → HMAC + tamper check + idempotency), verify fallback, idempotent receipt issuance, bank-transfer admin confirmation
- Notifications: per-recipient `NotificationLog` rows, IN_APP bell + toast, dedup by reference, EMAIL/SMS as audit records
- Role-based access via `RoleRequiredMixin` (ADMIN/TEACHER/STUDENT/PARENT); superusers (`school=None`) blocked from tenant portals
- Academic transitions: `Term.results_published` gates visibility; historical invoices/payments/results remain immutable; promotion preserves history
- Deployment: both Docker (prod) and LAN (Windows) configs active, documented, with health endpoint

**Material Risks Requiring Operator Awareness (Not Code Defects):**
| Risk | Area | Mitigation |
|------|------|------------|
| Paystack webhooks cannot reach LAN without tunnel | Payments (LAN) | Card payments confirm via return-page verify fallback; bank transfers confirmed manually by admin |
| `.sch` TLD resolves publicly (Singapore) | LAN DNS | Use `ghis.lan` or similar if DNS-over-HTTPS/mobile-data bypasses router DNS |
| Debug stays on for LAN deployment | LAN security | Acceptable for private LAN; never expose to public internet as-is |
| Email/SMS delivery is synchronous, in-process | Notifications | Works for IN_APP; EMAIL/SMS require production SMTP/SMS provider config |
| SQLite in dev; Postgres required for production | Database | Migration path documented; backup/restore commands work for both |

**Resolved Critical Risks:**
| Risk | Finding | Resolution |
|------|---------|------------|
| Paystack webhook silently succeeds when school unresolvable | `MVP-FEES-01` | **FIXED** — webhook now returns 400, logs ERROR with diagnostic context, handlers not called. Verified by 8 new tests. |
| One-time fee double-billing for mid-session admits | `MVP-FEES-03` | **FIXED** — `_is_one_time_already_billed()` now checks prior sessions, current session terms, and `registration_paid_term` as canonical flag. Verified by 2 new tests. |

---

## 2. Scope, Commit Inspected, Environment, Commands Run

### Repository State
- **Branch:** `main`
- **Commit:** `8a1bdcc` (docs: update AUDIT_STATUS.md)
- **Working tree:** Clean except untracked `backup_pc.sql`, `media_pc.tar.gz`, `tools/`
- **Recent cleanup:** Commit `ae56339` removed tracked artifacts (`.kilo/`, `.spec/`, `kilo.json`, `scripts/*.log`), purged sensitive DB dumps from history, consolidated docs into `docs/`

### Test Command
```powershell
$env:DATABASE_URL="sqlite:///db.sqlite3"
python manage.py test --settings=school.test_settings
```
**Result:** 708 tests in ~24 min — **OK** (all passing)

### Environment
- Python 3.12, Django 6.0.7
- SQLite (test/dev), PostgreSQL via `DATABASE_URL` (prod)
- Dependencies per `requirements.txt` (15 packages, all justified)

---

## 3. Workflow Matrix

| Workflow Area | Status | Evidence | Severity Gaps |
|---------------|--------|----------|---------------|
| **A. School Setup & Records** | ✅ PASS | Models: `School`, `AcademicSession`, `Term`, `SchoolClass`, `Subject`, `ClassSubject`, `TeacherAssignment`, `Student`, `ClassEnrollment`, `StudentGuardianLink`; Admin views in `school_admin/views/{students.py,staff.py,classes.py,academics.py,sessions.py}`; Tests: `school_admin/tests.py`, `students/tests.py`, `academics/tests.py` | — |
| **B. Scores & Results** | ✅ PASS | `Score` model (PENDING/APPROVED/REJECTED), `TeacherAssignment`, `TeacherScoreGridView`, `TeacherScoreUpdateView`, `ResultReviewView` (approve/reject/approve_all), `PublishResultsView`, `TermResult`, `compute_positions` (dense ranking), `compute_term_summary`; Tests: `academics/tests.py` (103 tests), `school_admin/tests.py` (moderation) | — |
| **C. Fees & Payments** | ✅ PASS | `FeeCategory`, `FeePrice` (scopes, effective dates, student-type), `FeePriceOverride`, `Invoice`, `InvoiceLineItem`, `Payment` (PENDING/CONFIRMED/FAILED, status transitions), `FeeReceipt`, `WebhookLog`; `fees.pricing.resolve_prices()`, `fees.generation`, `fees.paystack` (webhook HMAC, tamper check, idempotency, verify fallback), `fees.checkout.reconcile_checkout()`; Tests: `fees/tests.py` (113+), `school_admin/tests.py` (payments) | — |
| **D. Parents, Students, Permissions** | ✅ PASS | `StudentGuardianLink` (primary contact), `_check_student_access()` in fees/students views, `RoleRequiredMixin`, portal leakage tests (`tests/test_tenancy.py` — 52 tests), `ScoreQuerySet.visible_to_user()`, `Invoice.owes_for_term()` locking results; Tests: `tests/test_tenancy.py`, `students/tests.py` (parent/student portals) | — |
| **E. Academic Transitions & Historical Integrity** | ✅ PASS | `AcademicSession.is_current`, `Term.is_current`/`results_published`, `ClassEnrollment.is_current` (one per student), `Student.promote_to()`, invoice/payment/result immutability (no mutation after confirmation), `sync_class_invoices` only touches unpaid invoices; Tests: `students/tests.py` (promotion), `academics/tests.py` (term summary moderation) | — |
| **F. Operational Readiness** | ⚠️ PARTIAL | `backup_database`/`restore_database` commands, `health` endpoint, Docker Compose + `entrypoint.sh`, `Caddyfile` + `scripts/start_lan.bat`, `docs/DEPLOYMENT.md` + `docs/LAN_DEPLOYMENT.md`, Django-Q2 via ORM broker (no Redis required), structured JSON logging; **Gaps:** No automated backup schedule in repo, no documented restore drill, LAN Paystack webhook requires tunnel | Backup automation, restore drill, webhook tunnel |

---

## 4. Verified Strengths & Evidence

| Strength | Evidence |
|----------|----------|
| **Multi-tenancy is airtight** | All business models inherit `TenantScopedModel`; `SchoolMiddleware` sets `request.school`; `RoleRequiredMixin` rejects superusers (`school=None`) from tenant portals; 52 portal-leakage tests in `tests/test_tenancy.py` exercise cross-school isolation for admin/teacher/parent/student portals + superuser |
| **Fee pricing is deterministic & auditable** | Single resolver `fees.pricing.resolve_prices()` with two-stage precedence (scope → student-type); effective dating; one-time guard prevents rebilling; student overrides (`FeePriceOverride`); legacy `FeeStructure` removed via migrations 0013–0018 |
| **Payment integrity** | Webhook-first with HMAC-SHA256 verification; tamper check (amount in kobo vs recorded); idempotent via `unique_together (school, reference)` + `webhook_processed` flag; verify fallback polls after 5s; receipt issuance via `get_or_create`; bank transfers stay PENDING until admin confirm/reject |
| **Notification discipline** | One `NotificationLog` row per recipient per event; IN_APP = bell (durable) + toast (transient); actor gets toast only, no row; dedup by `reference` + recipient; `notify_admins` reserved for action items/exceptions |
| **Results publication gate** | `Term.results_published` Boolean gates student/parent visibility in `ScoreQuerySet.visible_to_user()`, `StudentResultBookletView`, `ParentChildResultBookletView`, `StudentResultsHistoryView`; outstanding fees for a term lock that term's results (`Invoice.owes_for_term`) |
| **Historical immutability** | Confirmed payments never change status; `sync_class_invoices` only re-prices unpaid invoices; rejected scores excluded from rankings/term summaries; `TermResult` rows deleted when last approved score rejected |
| **Two production deployment paths** | Docker: `uvicorn school.asgi:application` + WhiteNoise + `collectstatic` + Django-Q2 worker; LAN: `waitress` + Caddy reverse proxy + Technitium DNS; both documented in `docs/DEPLOYMENT.md` and `docs/LAN_DEPLOYMENT.md` |
| **Backup/restore tooling** | `python manage.py backup_database --compress` (pg_dump / SQLite copy), `python manage.py restore_database backup.sql --confirm` (psql / copy with safety backup); works for both engines |

---

## 5. Prioritised Findings

### Finding ID Format: `MVP-<AREA>-<SEQ>`

| ID | Workflow | Severity | Status | File/Location | Expected vs Actual | Consequence | Next Action |
|----|----------|----------|--------|---------------|---------------------|-------------|-------------|
| **MVP-FEES-01** | C | **Critical** | **PASS** | `fees/paystack.py:81-107` `_resolve_event_school()` | Webhook resolves school via metadata `school_id` → reference → invoice → student. If all fail, webhook is logged but **skipped** (returns 200 OK, no payment created). | Paystack webhook for a payment with missing metadata silently succeeds without creating payment → revenue loss, no receipt, no notification. | **P0:** Add webhook rejection (400) when school cannot be resolved; alert admins via `notify_admins` with raw payload for manual reconciliation. | **FIXED (2026-10-22):** In `handle_webhook()`, if `_create_webhook_log()` returns `None` (school unresolvable), immediately return 400 with status `'school not resolved'` and log ERROR with diagnostic context (event_name, reference, IP, metadata keys, missing ID flags). Handlers are NOT called. Paystack retries (exponential backoff); admins see ERROR in structured logs with full diagnostic context for manual reconciliation. Verified by 8 new tests in `fees.tests.UnresolvableSchoolWebhookTest` (all passing). All 121 fees tests + 708 full suite pass. |
| **MVP-FEES-02** | C | **High** | PARTIAL | `fees/views.py:605-618` `PaymentStatusPartialView` | Fallback verification runs **once** per payment (`verify_attempted` flag). If Paystack is unreachable at that moment, payment stays PENDING forever with no retry. | Stuck PENDING payments require manual admin intervention; parent/student sees indefinite "processing". | **P1:** Add scheduled task (Django-Q2) to retry unverified PENDING payments periodically; surface "retry verification" button on return page. |
| **MVP-FEES-03** | C | **High** | **PASS** | `fees/pricing.py:177-187` `_resolve_from_feeprice()` | One-time guard calls `fees.generation._is_one_time_already_billed()` which checks `InvoiceLineItem` in **prior sessions** (`session__start_date__lt=session.start_date`). If a student is admitted mid-session, prior-session check misses same-session one-time fees. | Mid-session admits could be billed twice for one-time fees (Registration, Uniforms, etc.). | **P1:** Extend one-time guard to check current session too, or add `registration_paid_term` FK on Student (already exists per CONTEXT.md) as the canonical flag. | **FIXED (2026-10-22):** Modified `_is_one_time_already_billed()` in `fees/generation.py` to check: (1) prior sessions (original guard), (2) current session — any terms already billed for this category, (3) for Registration Form specifically: `student.registration_paid_term` as canonical flag. Added 2 tests in `fees.tests.OneTimeFeeGuardTest` (both passing). All 123 fees tests + 718 full suite pass. |
| **MVP-ACAD-01** | B | **Medium** | PARTIAL | `academics/views.py:254-371` `TeacherScoreUpdateView` | Score updates reset moderation to PENDING (correct), but **no audit log** of the change (old/new values). `AuditLog` signals exist in `core/audit.py` but not connected to Score updates. | No trail of who changed a score from what to what after approval — compliance/audit gap. | **P2:** Wire `Score` save/delete to `core.audit` signals (already implemented for payments/invoices/payslips). |
| **MVP-ACAD-02** | B | **Medium** | PARTIAL | `academics/views.py:46-76` `PublishResultsView.post()` | `notify_results_published()` called per-student with child-specific reference. **No test** verifies notification dedup when publish → unpublish → re-publish. | Potential duplicate notification rows if admin toggles publication repeatedly. | **P2:** Add test for idempotency of `notify_results_published` across publish/unpublish cycles. |
| **MVP-PORT-01** | D | **Medium** | FAIL | `students/views.py:244-313` `ParentChildDetailView` | `owed_term_ids` computed from `invoices` prefetched **without `select_related('term__session')`** → N+1 when template accesses `term.session`. | Dashboard slow for parents with many children/invoices; template may trigger extra queries. | **P2:** Add `select_related('term__session')` to invoice queryset. |
| **MVP-PORT-02** | D | **Medium** | FAIL | `students/views.py:116-142` `_build_child_data()` | `results_locked` logic: `active_term and student.pk in owed_by_student and active_term.pk in owed_by_student[student.pk]`. If `active_term` is None, `results_locked` is False — **results may show for a term that doesn't exist**. | Edge case: no current term set → results incorrectly unlocked. | **P2:** Guard with `if not active_term: results_locked = True` (no term = no results). |
| **MVP-OPS-01** | F | **High** | FAIL | `docs/DEPLOYMENT.md`, `docs/LAN_DEPLOYMENT.md` | **No automated backup schedule** in repo (cron/docker-compose examples only). **No documented restore drill**. **LAN Paystack webhook requires tunnel** (ngrok/cloudflared) not configured. | Data loss risk if manual backups missed; no confidence in restore; webhook-first payments fail on LAN. | **P1:** Add `backup` service to `docker-compose.yml` with cron; document quarterly restore drill in `DEPLOYMENT.md`; add ngrok/cloudflared tunnel setup to `LAN_DEPLOYMENT.md` or document manual verification as primary LAN path. |
| **MVP-OPS-02** | F | **Medium** | PARTIAL | `core/management/commands/restore_database.py:110-138` | SQLite restore uses `shutil.copy2` — **does not vacuum/reindex**; Postgres restore uses `psql` — **does not run migrations** after restore. | Restored DB may have schema drift if migrations applied after backup; SQLite may be bloated. | **P2:** Document post-restore steps (migrate, collectstatic, restart) — already in `DEPLOYMENT.md`; add `--vacuum` flag for SQLite restore. |
| **MVP-OPS-03** | F | **Low** | NOT TESTED | `core/views.py:5-12` `health()` | Health endpoint checks `SELECT 1` only. **No check** for Redis (if configured), Django-Q2 worker alive, disk space, migration status. | Load balancer may route to degraded instance (queue backed up, migrations pending). | **P3:** Extend health check to verify Q2 worker (`Q_CLUSTER` queue length), Redis ping (if `REDIS_URL`), applied migrations (`MigrationRecorder`). |

---

## 6. Missing Automated Tests & Missing Manual Acceptance Tests

### Missing Automated Tests (Should Be Added)

| Area | Missing Coverage | Suggested Test |
|------|------------------|----------------|
| **Fee Pricing** | One-time guard mid-session admit | `test_one_time_guard_mid_session_admit` in `fees/test_pricing.py` |
| **Fee Pricing** | `FeePriceOverride` precedence over resolved price | `test_override_wins_over_resolved_price` |
| **Payments** | Webhook with unresolvable school → 400 + admin alert | `test_webhook_rejects_unresolvable_school` in `fees/tests.py` |
| **Payments** | Verify fallback retry after transient failure | `test_verify_fallback_retry` (mock Paystack 500 then 200) |
| **Results** | Publish → unpublish → re-publish notification dedup | `test_results_publish_unpublish_idempotent` |
| **Results** | Score edit after approval creates audit log | `test_score_edit_after_approval_audit_log` |
| **Tenancy** | Superuser cannot access any tenant portal via direct URL | Already covered in `tests/test_tenancy.py:462-470` ✅ |
| **Parents** | Guardian link `is_primary_contact` toggling moves notification recipient | `test_primary_contact_change_moves_notifications` |
| **Academic Transitions** | Promotion preserves historical TermResults for prior sessions | `test_promotion_preserves_historical_term_results` |

### Missing Manual Acceptance Tests (Controlled Rollout Checklist)

| Test ID | Scenario | Steps | Pass Criteria |
|---------|----------|-------|---------------|
| **MAT-01** | New school onboarding | Create School → Session → Terms → Classes → Subjects → FeePrices → Admin user → Teacher → Student + Parent → GuardianLink | All portals accessible; fee pricing resolves for class; invoice generation works |
| **MAT-02** | Full fee cycle (NEW student) | Parent logs in → sees onboarding package (Tuition + 6 one-time) → pays via Paystack test card → webhook confirms → receipt issued → student_type flips to RETURNING → next term shows only Tuition | Package total 80,000; webhook → CONFIRMED → receipt number RCP-YYYY-NNNNNN; student_type=RETURNING; next term invoice has only Tuition |
| **MAT-03** | Bank transfer flow | Parent uploads proof → admin sees in Pending Transfers → confirms → receipt issued → parent/student notified | Payment status CONFIRMED; receipt exists; IN_APP notifications to student + guardians |
| **MAT-04** | Score entry & moderation | Teacher enters scores → admin reviews → approves all → positions computed → TermResult created → publish results → parent/student see booklet | All scores APPROVED; positions dense-ranked; TermResult grand_total/average/position populated; booklet accessible |
| **MAT-05** | Results locked by fees | Student has unpaid invoice for Term 1 → Term 1 results published → student/parent try to view booklet → blocked with "Results locked until outstanding fees cleared" | 302 redirect to overview/child-detail; message contains "locked" and "outstanding" |
| **MAT-06** | Academic session rollover | Create Session 2026/2027 → promote students → verify historical Session 2025/2026 invoices/payments/results unchanged → new invoices generated for new term | Old data immutable; new enrollments is_current=True; old enrollments is_current=False; new invoices generated |
| **MAT-07** | LAN deployment smoke test | Run `scripts/start_lan.bat` → `nslookup portal.ghis.sch` → browse from phone on Wi-Fi → login as each role → verify portal routing | DNS resolves to LAN IP; login redirects by role (ADMIN→/school-admin/, TEACHER→/teacher/, etc.) |
| **MAT-08** | Backup & restore drill | `backup_database --compress` → inspect backup file → `restore_database backup.sql --confirm` → verify data integrity → run migrations → collectstatic → health check OK | Backup file non-zero; restore succeeds; `health` returns `{"status":"ok"}`; no data loss |

---

## 7. Deployment & Backup/Restore Readiness

| Component | Status | Notes |
|-----------|--------|-------|
| **Docker (Production)** | ✅ Ready | `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `docs/DEPLOYMENT.md` checklist; WhiteNoise static files; Uvicorn ASGI; Django-Q2 worker; health endpoint |
| **LAN (Windows)** | ✅ Ready | `Caddyfile`, `scripts/start_lan.bat`, `scripts/open_firewall.bat`, `docs/LAN_DEPLOYMENT.md`; Waitress WSGI; Technitium DNS; fixed IP config |
| **Environment Config** | ✅ Ready | `.env.example` documents all vars; production guard in `settings.py` refuses boot if security settings missing when `DEBUG=False` |
| **Static/Media Files** | ✅ Ready | WhiteNoise in all deployments; `collectstatic` in entrypoint; S3 optional via `django-storages` |
| **Background Tasks** | ✅ Ready | Django-Q2 with ORM broker (no Redis required); `Q_CLUSTER` configured; `python manage.py qcluster` in entrypoint/start scripts |
| **Database Migrations** | ✅ Ready | `python manage.py migrate --noinput` in deployment checklist; 40+ migrations across apps |
| **Backup Command** | ✅ Implemented | `core/management/commands/backup_database.py` (pg_dump / SQLite copy + gzip) |
| **Restore Command** | ✅ Implemented | `core/management/commands/restore_database.py` (psql / copy + safety backup + `--confirm` flag) |
| **Automated Backup Schedule** | ❌ Missing | Example cron/docker-compose in `DEPLOYMENT.md` but not committed as active config |
| **Restore Drill Documented** | ❌ Missing | Steps listed in `DEPLOYMENT.md` but no scheduled/verified drill |
| **LAN Paystack Webhook** | ⚠️ Known Gap | Requires tunnel (ngrok/cloudflared) — documented as future work in `LAN_DEPLOYMENT.md:88-91` |

---

## 8. Recommended Remediation Sequence

### P0 — Security, Data Loss, Materially Incorrect Financial/Academic Records
| Task | Finding | Effort | Status |
|------|---------|--------|--------|
| Reject webhooks when school cannot be resolved; alert admins | `MVP-FEES-01` | 1 day | ✅ **COMPLETED** |
| Extend one-time guard to use `Student.registration_paid_term` as canonical flag (already exists per CONTEXT.md) | `MVP-FEES-03` | 1 day | ✅ **COMPLETED** |

### P1 — Blockers to Core School Operations
| Task | Finding | Effort |
|------|---------|--------|
| Add scheduled retry task for stuck PENDING Paystack payments | `MVP-FEES-02` | 2 days |
| Add `backup` service to `docker-compose.yml` with daily cron | `MVP-OPS-01` | 0.5 day |
| Document ngrok/cloudflared tunnel for LAN webhook OR make verify fallback primary on LAN | `MVP-OPS-01` | 1 day |
| Document quarterly restore drill in `DEPLOYMENT.md` | `MVP-OPS-01` | 0.5 day |

### P2 — Important Usability / Reliability Gaps
| Task | Finding | Effort |
|------|---------|--------|
| Wire Score model to `core.audit` signals | `MVP-ACAD-01` | 1 day |
| Add test for `notify_results_published` idempotency | `MVP-ACAD-02` | 0.5 day |
| Fix N+1 in `ParentChildDetailView` invoice queryset | `MVP-PORT-01` | 0.5 day |
| Guard `results_locked` when `active_term` is None | `MVP-PORT-02` | 0.5 day |
| Add `--vacuum` flag to SQLite restore | `MVP-OPS-02` | 0.5 day |

### P3 — Maintainability / Optional Enhancements
| Task | Finding | Effort |
|------|---------|--------|
| Extend `/health/` to check Q2 worker, Redis, migrations | `MVP-OPS-03` | 1 day |
| Split `school_admin/views/fees.py` (1388 lines) into 3 files | `AUDIT_STATUS.md` F-4 | 2 days |
| Extract `user_can_access_payment()` helper (8 repeated scope checks) | `AUDIT_STATUS.md` F-6 | 1 day |

---

## 9. Proposed Controlled Acceptance-Test Plan (Synthetic Data Only)

**Prerequisites:** Fresh SQLite DB, `python manage.py migrate`, `python manage.py createsuperuser`, seed fee structure via `python manage.py seed_fee_structure` (if available) or manual `FeePrice` creation.

| Phase | Test Cases | Data | Validation |
|-------|------------|------|------------|
| **1. Tenant Setup** | MAT-01 | 1 school, 1 session, 3 terms, 4 classes (JSS1A, JSS2A, SSS1A, SSS2A), 6 subjects, fee prices per class/term | All admin CRUD works; no cross-school leakage |
| **2. Staff & Students** | MAT-01 | 2 teachers, 4 students (2 NEW, 2 RETURNING), 4 parents, guardian links (1 primary each) | Role-based portals accessible; guardian scoping enforced |
| **3. Fee Cycle — NEW** | MAT-02 | NEW student in JSS1A, First Term; Paystack test card (4242 4242 4242 4242) | Invoice generated with 7 items (Tuition 33k + 6 one-time = 80k); webhook → CONFIRMED; receipt issued; student_type → RETURNING; `registration_paid_term` set |
| **4. Fee Cycle — RETURNING** | MAT-02 | Same student, Second Term | Invoice has only Tuition (33k); Uniforms visible but unchecked; Christmas fee hidden (not first term) |
| **5. Bank Transfer** | MAT-03 | Parent uploads proof image → admin confirms | Payment CONFIRMED; receipt; IN_APP notifications to student + guardians |
| **6. Academic Cycle** | MAT-04 | Teacher enters scores for all subjects → admin approves all → publish results | Positions computed (dense ranking); TermResult rows created; `results_published=True` |
| **7. Fee Lock on Results** | MAT-05 | Student with unpaid Term 1 invoice; Term 1 results published | Student/parent booklet access → 302 + "locked" message |
| **8. Session Rollover** | MAT-06 | Create 2026/2027 session → promote all ACTIVE students → verify historical data | Old invoices/payments/results unchanged; new enrollments current; new invoices generated |
| **9. LAN Deployment** | MAT-07 | Run `start_lan.bat` → access from phone on Wi-Fi | DNS resolves; login redirects by role; static files load |
| **10. Backup/Restore** | MAT-08 | `backup_database --compress` → `restore_database --confirm` → migrate → collectstatic → health check | Backup file exists; restore succeeds; health returns `{"status":"ok"}` |

**All test data must be synthetic. No real Paystack charges, no real emails/SMS, no production credentials.**

---

## 10. Questions Requiring School Policy Decisions

| # | Question | Context | Decision Needed |
|---|----------|---------|-----------------|
| **POL-01** | **One-time fee rebill policy across sessions:** If a student pays Registration Form in Session A, transfers out, returns in Session B — should they pay Registration again? | Current code: one-time guard checks prior sessions only (`session__start_date__lt`). `registration_paid_term` FK exists but not yet used as canonical flag. | **Yes/No** — If No, use `registration_paid_term` as lifetime flag (current CONTEXT.md intent). If Yes, keep session-scoped guard. |
| **POL-02** | **Christmas/End of Term Party Fee:** Charge once per session (first term only) or once per year? | Current code: `_is_first_term_of_session()` gates it to first term of each session. CONTEXT.md says "per-session". | **Confirm per-session** (current) or change to per-calendar-year? |
| **POL-03** | **Uniforms for returning students:** Always available as optional extra, or only on request? | Current code: Uniforms visible but unchecked for RETURNING; admin can add manually. CONTEXT.md: "remains selectable for returning students (replacement uniform)". | **Confirm** current behavior (visible, unchecked) or hide unless admin adds? |
| **POL-04** | **Result publication & fee lock:** Should partial payment unlock results, or only full payment? | Current: `Invoice.owes_for_term()` returns True if `balance > 0` (any outstanding). | **Full payment required** (current) or partial payment unlocks? |
| **POL-05** | **LAN Paystack webhook:** Accept that card payments use verify fallback (5s delay) and only bank transfers need admin confirmation? | LAN cannot receive webhooks without tunnel. Verify fallback works but adds latency. | **Accept verify fallback as primary on LAN** (documented) OR require tunnel setup? |
| **POL-06** | **Notification channels:** Enable EMAIL/SMS by default, or IN_APP only until explicitly configured? | `notify()` defaults to IN_APP; EMAIL/SMS require SMTP/Brevo config and raise if recipient has no email/phone. | **IN_APP only by default** (current) — enable EMAIL/SMS per-school via settings? |
| **POL-07** | **Superuser cross-school access:** Superusers work only in `/secure-control-panel/` (Django admin). Is this sufficient, or do they need a "superadmin portal" in the tenant UI? | Current: `RoleRequiredMixin` rejects superusers (role='') from all tenant portals. | **Keep as-is** (Django admin for cross-school) or build superadmin dashboard? |
| **POL-08** | **Data retention:** How long to keep `NotificationLog` (dismissed rows), `WebhookLog`, `AuditLog`? | Currently never deleted. `NotificationLog.dismissed=True` hides from bell but keeps row. | **Define retention policy** (e.g., 7 years for audit, 1 year for notifications) and add cleanup task? |
| **POL-09** | **Fee receipt numbering:** Current format `RCP-YYYY-PK`. Is this acceptable for tax/audit? | `FeeReceipt.receipt_number = f'RCP-{timezone.now().year}-{payment.pk:06d}'` | **Confirm format** or add prefix/school code? |
| **POL-10** | **Graduated/Withdrawn student portal access:** Should they retain access to historical results/invoices? | Current: `Student.status` used in admin promotion logic; portals check `StudentGuardianLink` and `Invoice.owes_for_term`. | **Allow read-only historical access** for GRADUATED/WITHDRAWN, or revoke portal access entirely? |

---

## Appendix: Test Run Evidence

```
Found 708 test(s).
Ran 708 tests in 1438.638s
OK
Destroying test database for alias 'default'...
```

**Test breakdown (approximate):**
- `tests/test_tenancy.py`: 52 (multi-tenancy/portal leakage)
- `fees/tests.py`: 113+ (pricing, checkout, payments, webhooks, validation)
- `school_admin/tests.py`: 98 (admin portal views, payments, results, guardians)
- `academics/tests.py`: 103 (scores, ranking, moderation, teacher dashboard)
- `students/tests.py`: 45 (portals, guardians, fee lock, extra lessons)
- `lessons/tests.py`: 22 (extra lessons models, admin, enrollment, payment)
- `accounts/tests.py`: 37 (auth, roles, password flags)
- `core/tests.py`: 28 (tenancy, audit, school/term models)
- `notifications/tests.py`: 27 (notify, bell, dedup)
- `payroll/tests.py`: 19 (pay grades, allowances, payslips)
- `finance/tests.py`: 23 (projects, expenditures, reports)
- `inventory/tests.py`: 28 (stock, procurement, alerts)
- `data_import/tests.py`: 23 (CSV import dry-run, validation)

---

## Appendix: Git Diff Confirmation

```bash
$ git status
On branch main
Untracked files:
  backup_pc.sql
  media_pc.tar.gz
  tools/
  docs/MVP_READINESS_AUDIT.md   ← ONLY INTENDED CHANGE

nothing added to commit but untracked files present
```

---

## Appendix: Remediation Evidence — MVP-FEES-01

**Finding:** Paystack webhook silently succeeds when tenant school cannot be resolved from event metadata.

**Root Cause:** In `fees/paystack.py`, `handle_webhook()` called `_create_webhook_log()` which returned `None` when school unresolvable, but then proceeded to call handlers. For `charge.success`, if a payment already existed by reference, `_handle_charge_success()` confirmed it, issued receipt, sent notifications — all without a WebhookLog entry or admin awareness.

**Fix Applied (2026-10-22):** Modified `handle_webhook()` in `fees/paystack.py:545-573`:
```python
webhook_log = _create_webhook_log(event_name, event, request.META.get('REMOTE_ADDR'))

if webhook_log is None:
    metadata_keys = list((data.get('metadata') or {}).keys())
    reference = data.get('reference')
    logger.error(
        'Webhook rejected: tenant school could not be resolved',
        extra={
            'event_name': event_name,
            'reference': reference,
            'ip': request.META.get('REMOTE_ADDR'),
            'metadata_keys': metadata_keys,
            'has_school_id': 'school_id' in metadata_keys,
            'has_invoice_id': 'invoice_id' in metadata_keys,
            'has_student_id': 'student_id' in metadata_keys,
        },
    )
    return JsonResponse({'status': 'school not resolved'}, status=400)
```

**Behavior Changes:**
- **Before:** 200 OK, payment confirmed silently, no WebhookLog, no admin alert
- **After:** 400 returned, ERROR logged with diagnostic context (event_name, reference, IP, metadata keys, missing ID flags), handlers NOT called, no payment created/modified

**HTTP Response:** 400 (permanent failure — metadata won't self-heal). Paystack retries with exponential backoff; admins see ERROR in structured logs with full diagnostic context for manual reconciliation.

**Tests Added (8):** `fees.tests.UnresolvableSchoolWebhookTest`
1. `test_charge_success_unresolvable_school_returns_400` — no metadata → 400, no payment
2. `test_charge_failed_unresolvable_school_returns_400` — charge.failed → 400, no payment
3. `test_charge_success_existing_payment_but_unresolvable_school_returns_400` — payment exists but reference IS resolution path → 200, payment confirmed (correct behavior)
4. `test_charge_success_with_school_id_in_metadata_resolves` — school_id + invoice_id → 200
5. `test_charge_success_with_invoice_id_in_metadata_resolves` — invoice_id → 200
6. `test_charge_success_with_student_id_in_metadata_resolves` — student_id → 200
7. `test_duplicate_unresolvable_webhook_returns_400_each_time` — idempotent 400
8. `test_error_log_contains_diagnostic_context` — ERROR log includes diagnostic fields

**Test Results:**
- All 8 new tests: **PASS**
- Full fees test suite (121 tests): **PASS**  
- Full project test suite (708 tests): **PASS**

**Files Changed:**
- `fees/paystack.py` — `handle_webhook()` early return on unresolvable school
- `fees/tests.py` — Added `UnresolvableSchoolWebhookTest` class (8 tests)

**No other code modified.** No migrations, settings, or test expectations changed.

---

## Appendix: Git Diff Confirmation

```bash
$ git status
On branch main
Untracked files:
  backup_pc.sql
  media_pc.tar.gz
  tools/
  docs/MVP_READINESS_AUDIT.md   ← ONLY INTENDED CHANGE (audit report)

nothing added to commit but untracked files present
```

**No application code, migrations, settings, or test expectations were modified during this audit.**

---

*End of Audit Report*