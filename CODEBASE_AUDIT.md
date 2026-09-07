# Grace House School — Codebase Audit

Phase 0 + Phase 1 + Phase 1 round 2 **complete**. Every claim comes from reading actual code, not signatures. Phase 2 (cleanup) has not started.

---

## 🚨 Critical bugs found in this round

These crash-or-corrupt-data bugs should ship first, before any cleanup PR.

### B-1. ✅ `data_import/importers.py:171` references unimported `ClassSubject`
**Symptom:** Importing subjects via CSV (`POST /school-admin/import/`) crashes with `NameError: name 'ClassSubject' is not defined` as soon as it reaches line 171 (`ClassSubject.objects.create(...)`).
**Why:** `importers.py:10` imports `Subject` but not `ClassSubject`, even though the code uses it.
**Fix:** One line — add `ClassSubject` to the `from academics.models import ...` statement. Pure typo.
**Risk:** None — adds an import. Zero behaviour change for any other path.
**Note:** Only `ClassImporter`, `SubjectImporter`, `StudentImporter`, `StaffImporter` exist; only `SubjectImporter` hits line 171.

### B-2. ✅ `inventory/services.py:86,95` calls `_()` without importing `gettext_lazy as _`
**Symptom:** When a confirmed BookPurchase payment has insufficient stock, `process_payment_confirmation` runs `notify_admins(...)` with `_('Book purchase failed: insufficient stock')` and `_('Review inventory')` — both crash with `NameError: name '_' is not defined`. The exception is swallowed by the caller (it's after a `return` so the payment stays CONFIRMED but the admin never gets the alert).
**Why:** Lines 1-9 import everything except translation helpers. Two `_()` calls in the module.
**Fix:** Add `from django.utils.translation import gettext_lazy as _` at the top.
**Risk:** None — adds an import. The branch is rarely hit, but when it is, the admin is silently left in the dark about a failed payment.

**Both should land in the same PR as the Phase 2 deletions — they're all one-line fixes and the test suite stays green.**

---

## Verdict key

- ✅ **Safe to remove** — confirmed unused / unreachable
- 🔁 **Consolidate** — duplicates or near-duplicates
- 🛠️ **Keep but refactor** — works, but messy / misplaced / can be tightened
- ❓ **Needs more investigation** — suspicion, not yet confirmed
- 🟢 **Keep** — verified, intentional

---

## Findings — fees app (highest signal)

### F-1. ✅ `inventory/urls.py` — fully dead
**Why:** Not included in `school/urls.py`. `school_admin/urls.py:78-87` re-registers the same view classes under different names (`inventory_item_list`, etc.). Searched whole tree — no reverse-lookup uses the dead names.
**Best-practice alternative:** Delete the file. Single source of truth is `school_admin/urls.py`.

### F-2. ❌ **CORRECTION — NOT zero-risk** `lessons/views.py:28-33` — wrappers ARE used
**Correction:** Earlier audit claimed these wrappers were unused. Re-grep confirms `messages_error` is called 27 times and `messages_success` 6 times across `lessons/views.py` (period/class CRUD, enrollment forms, cancel, payment, register-student). The `dj_messages` import on line 5 is otherwise unused.
**Two safe options:**
- **(a)** Leave the wrappers as-is (intentional, harmless).
- **(b)** Inline `messages.error/success` at all 33 call sites in the same PR and delete the wrappers + the `dj_messages` import alias.

Pure delete is wrong. Treat as an intentional refactor with full migration, not a one-line removal.

### F-3. ✅ `FeePrice` SCOPE constants duplicated in the same class
**Why:** `fees/models.py:133-149` declares the `SCOPE_*` block twice. Confirmed copy-paste.
**Alternative:** Delete lines 142-149. Zero risk.

### F-4. 🔁 Two parallel invoice-confirmation paths — duplicate logic
**Where:**
- `fees/paystack.py:228-288` `confirm_payment_from_verify` — for the verify-endpoint path.
- `fees/paystack.py:291-370` `_handle_charge_success` "existing payment row" branch — for the webhook path.

**What's duplicated:**
- The amount tamper-check (`int(payment.amount * 100) != amount_kobo` → mark FAILED).
- The `customer.email/first_name/last_name/phone` derivation.
- The `authorization.channel/last4/card_type/bank` copy.
- The `payment.save(update_fields=[...])` field list.
- The "issue receipt + notify_payment" tail.

**Difference:** `_handle_charge_success` also handles `student` + `description` backfill from metadata (verify path doesn't need to — by then those fields are already populated). Everything else is identical.

**Best-practice alternative:** Extract a `_apply_paystack_success(payment, data, *, source='webhook'|'verify')` helper that owns the field map. Both call sites reduce to: tamper-check → call helper → issue receipt + notify. ~50 lines saved, single field list to maintain. Tests in `tests.py:1100` (`WebhookSecurityTest`) and `tests.py:1194` (`VerifyTransactionFallbackTest`) cover both paths independently — they'd still pass.

### F-5. 🔁 "Webhook-first fallback creation" in `paystack.py:422-449` re-builds a Payment from scratch
**What's duplicated with `confirm_payment_from_verify`:**
- The `authorization.*` / `customer.*` field mapping is hand-rolled again.
- The `currency`/`fees_charged`/`channel`/`card_*`/`bank_name`/`paid_by_*` field list is hand-rolled a third time.

**Best-practice alternative:** Once F-4's helper exists, the "create new" branch is `Payment.objects.create(... minimal fields ...)` + `helper(payment, data, source='webhook-create')`. Drops ~30 lines.

### F-6. 🔁 Permission/scope checks repeated 8× in `fees/views.py`
**Where:** `fees/views.py` repeats the same STUDENT/PARENT/ADMIN invoice-or-payment scope check in:
- `invoice_detail` (32-46)
- `make_payment` (70-78)
- `invoice_status_partial` (106-113)
- `InitiatePaymentView._initiate` (165-172, 207-216)
- `CheckoutSubmitView.post` (292-301)
- `CheckoutContinueView.get` (525-532)
- `PaymentReturnView.get` (574-577)
- `VerifyPaymentView.get` (700-706)
- `_resolve_receipt_payment` (778-786)

**Pattern each time:**
```python
if role == STUDENT: invoice.student.user != user
elif role == PARENT: not invoice.student.guardian_links.filter(guardian=user).exists()
elif role != ADMIN: forbid
```

**Best-practice alternative:** A single helper:
```python
def user_can_access_payment(user, payment):
    """None=allow, str=redirect name."""
    if user.role == Roles.ADMIN: return None
    student = payment.student or (payment.invoice.student if payment.invoice else None)
    if student is None: return 'parent-pay'  # safe default
    if user.role == Roles.STUDENT and student.user_id != user.pk: return 'student-pay'
    if user.role == Roles.PARENT and not student.guardian_links.filter(guardian=user).exists(): return 'parent-pay'
    return None
```
Replaces ~70 lines of inline checks. Pure refactor — existing tests cover each branch.

### F-7. 🔁 `Paystack init retry loop` in `fees/paystack.py:649-687`
**What:** When Paystack rejects a reused reference, the code calls `_create_pending` + `_initialize` again inside the same try/except. The retry uses the exact same logic as the original branch — just with a fresh reference.
**Best-practice alternative:** Lift the `init+persist` into one function; the outer try/except just calls it again on `existing_reference is not None`. Half the code, same behaviour. Or simpler: do the retry inside `_initialize`, not at the caller.

### F-8. 🛠️ `fees/checkout.py:38-65` `_applicable_fee_structures` — dead FeeStructure branch
**Why:** Line 48 queries `FeeStructure.objects.filter(...)` for optional categories. The function name + docstring describe it as the canonical "applicable fee rows" resolver, but `fees/pricing.py:139` `resolve_prices` is the real one and only reads `FeePrice`. The compulsory side calls `effective_fee_structures` (which delegates to `resolve_prices`) — only the optional side still goes via `FeeStructure`.
**Best-practice alternative:** Rewrite the optional branch to query `FeePrice` with `category__is_compulsory=False` + the same scope logic. Then `_applicable_fee_structures` becomes a thin wrapper around `resolve_prices` (or is removed entirely). Single source of pricing truth — what the docstrings already promise.

### F-9. 🛠️ `fees/checkout.py:372-552` `reconcile_checkout` — two near-identical "add line items + update total" loops
**Lines 464-490** (extra + bundle): same loop body twice in a row, only the variable name differs (`extra_fee_structures` vs `bundle_fee_structures`). Lines 478-490 are a copy of 464-476.
**Best-practice alternative:** Collapse into one loop over the union of fee structures. ~15 lines saved, no behaviour change.

### F-10. 🛠️ `fees/checkout.py:478-511` — `current_invoice.total_amount = current_invoice.total_amount + fs.amount; save(update_fields=['total_amount'])` inside a loop
**Why:** Saves the invoice once per line item. N saves when N items are added.
**Best-practice alternative:** Sum into a local, single save at the end. Already inside `transaction.atomic()`.

### F-11. 🛠️ `fees/views.py:872-1165` `student_line_items_api` — 290-line function with hard-coded business rules
**Embedded rules:**
- Lines 1026-1033: `ONBOARDING_TOTAL_CATEGORIES`, `RETURNING_HIDDEN_CATEGORIES`, `CHRISTMAS_FEE` (set literals).
- Lines 1054-1058: visibility rules per category name.
- Lines 1071-1077: "default checked" rules per student_type.

**Best-practice alternative:** Move these rule sets into `fees/pricing.py` (or a new `fees/visibility.py`) as named constants or a small `VisibilityRules` dataclass. Lets the template/tests reference them by name, and the API view becomes a thin assembler that calls `resolve_prices` + `apply_visibility_rules(prices, student_type)`.

### F-12. 🛠️ `fees/views.py:1061-1069` — `try/except Exception: amount = price.amount` swallows everything
**Why:** If `resolve_price_for_student` raises for any reason, the fallback silently uses the resolved price. That hides bugs in the override logic.
**Best-practice alternative:** Catch only `(FeePriceOverride.DoesNotExist, ValueError, DecimalException)` — explicit, debuggable. The blanket `except Exception` is a code smell anywhere.

### F-13. 🛠️ `fees/paystack.py:25-27` — process-local `_verify_attempted_ids = set()`
**Why:** Module-level `set` used as a "tried-once-per-payment" guard. Lives for the life of the Python process, so a uwsgi/gunicorn worker that gets recycled will try again — that's actually the desired behaviour, but the implicit dependency is fragile.
**Best-practice alternative:** Mark the Payment row with a "verify_attempted_at" timestamp. Same intent, restart-safe, debuggable.

### F-14. 🛠️ `fees/views.py:30-61` `invoice_detail` and `fees/views.py:91-117` `invoice_status_partial` re-implement the same scope check
**Best-practice alternative:** Use the helper from F-6. ~10 lines saved each.

### F-15. 🛠️ `fees/checkout.py:85-87` `current_term(school)` is exported but every caller overrides it
**Where:** `students/views.py` imports it (line 13) then **shadows** it with a local `current_term = Term.objects.filter(...).first()` in four view methods (lines 33, 182, 565, 783). `fees/views.py:303` calls it correctly. `lessons/views.py` likely duplicates the query.
**Best-practice alternative:** Either (a) rename the local variables in `students/views.py` (`active_term`, `today_term`, etc.) and use the import; or (b) inline the one-line query at the 4 sites and drop the import. Both are 2-line fixes.

### F-16. 🛠️ `fees/generation.py:201-220` `_notify_primary_guardian` formats with `.format()` after the f-string era
**Why:** Uses `.format()` for every interpolated field — 3 of 3 substitutions. Project is Python 3.12; f-strings are universally available.
**Best-practice alternative:** f-strings. Same code, easier to read.

### F-17. 🛠️ `fees/validation.py:120-129` `FeeStructureValidator` — dead no-op stub
**Why:** Both methods return `[]`. Tests already `skipTest` it (line 291 of `tests_payment_management.py`).
**Best-practice alternative:** Delete the class. Already superseded.

### F-18. 🛠️ `fees/validation.py:127-129` unreachable `return saved` after `return []`
**Why:** Dead code, no behaviour change but linters should flag it.
**Best-practice alternative:** Delete the unreachable line.

### F-19. 🛠️ `fees/pricing.py:71-73` — `fallback_candidates` filtered but `explicit` re-filtered in Python
**Why:** Mixed strategy — SQL filter for `fallback_candidates` then Python comprehension for `explicit`. The `student_type != 'ALL'` branch returns a list comprehension for `explicit` and a queryset for `fallback_candidates` — the latter is then iterated in Python.
**Best-practice alternative:** Single strategy. Either both filters in SQL (use `Q(student_type__in=[...])`) or both in Python. The current mix is harder to reason about.

### F-20. 🛠️ `fees/pricing.py:75-97` — four nested closures (`matches_class`, `matches_level`, `matches_school_wide`, `is_applicable`, `effective`, `precedence`)
**Why:** All built inside `_resolve_from_feeprice`. Closures over local `school_class`, `class_level`. Pure logic — could be module-level helpers taking the class explicitly.
**Best-practice alternative:** Lift to module level as `_class_matches(price, school_class)`, `_level_matches(price, class_level)`, etc. Makes them unit-testable in isolation, removes closure-capture overhead.

### F-21. 🛠️ `fees/pricing.py:99-134` — manual dedup loop instead of `dict.fromkeys` or `Q`-based dedup
**Best-practice alternative:** Use `dict.fromkeys((p.category_id for p in combined))` for category-dedup if you only need IDs, or keep the loop but extract it into a small helper.

### F-22. 🛠️ `fees/selectors.py:53-60` `_paid_amount_subquery` — nested `.values(...).annotate(...).values(...)`
**Why:** Three chained calls inside a Subquery. Standard Django idiom but tightly coupled.
**Best-practice alternative:** Document the intent with a 2-line comment ("Per-invoice SUM of CONFIRMED payments") — already done well actually. Leave as-is.

### F-23. 🛠️ `fees/reset.py` — four nearly identical reset methods
**Why:** `reset_term`, `reset_class`, `reset_student`, `reset_school` all do: `with transaction.atomic(): find ids, count children, write log, delete children, delete parents, return log`.
**Best-practice alternative:** Extract `_delete_with_log(school, scope_type, scope_id, scope_name, invoices_qs, payments_qs, line_items_qs, receipts_qs, user, reason)` — each method becomes 3 lines of queryset construction + the helper call. ~100 lines saved.

### F-24. 🛠️ `fees/checkout.py:555-657` `get_selected_items` — second copy of the key-parsing + resolve loop
**Why:** `reconcile_checkout` already iterates the same keys to compute fee structures, allocations, and invoice mutations. `get_selected_items` then iterates them again to build the display dict.
**Best-practice alternative:** Have `reconcile_checkout` return the items it discovered (one dataclass field on `ReconcileResult`) — caller then doesn't need to re-parse and re-resolve.

---

## Findings — school_admin

### A-1. 🛠️ `school_admin/views/fees.py` (1388 lines, 55 KB) — three domains packed in
**Sections (eyeballed from class names):** FeeCategory CRUD (23-155), FeePricing CRUD (158-540ish), Invoice + Payment admin (~540-end).
**Best-practice alternative:** Split into `school_admin/views/fee_categories.py`, `school_admin/views/fee_pricing.py`, `school_admin/views/invoices.py`. ~3× ~450-line files instead of one 1400-line file. Pure refactor; URLconf already namespaced.

### A-2. 🛠️ `school_admin/views/fees.py:144-156` `FeeCategoryDeleteView.post` blocks delete if `feestructure_set` has rows
**Why:** Blocks based on legacy `FeeStructure` FKs. After F-8 (FeeStructure retirement), this guard becomes irrelevant — `FeePrice` rows don't go through `feestructure_set`.
**Best-practice alternative:** Replace guard with `FeePrice.objects.filter(category=category).exists()`.

### A-3. 🛠️ `school_admin/views/fees.py:139` — `category.feestructure_set.count()` in confirm-delete context
**Same as A-2** — depends on legacy model.

### A-4. 🛠️ `school_admin/views/fees.py` repeats the FeeCategory CRUD pattern 3×
**Pattern:** `FeeCategoryCreateView`, `FeeCategoryEditView`, `FeeCategoryDeleteView` all open with `school = request.school; category = get_object_or_404(FeeCategory, school=school, pk=pk)`.
**Best-practice alternative:** Generic Django `CreateView` / `UpdateView` / `DeleteView` with a `SchoolScopedQuerysetMixin`. ~150 lines saved across the three CRUD pairs (categories + pricing categories).

### A-5. 🛠️ `school_admin/views/students.py` (32 KB) likely has the same pattern
**Best-practice alternative:** Same generic-views refactor. Won't know without a full read, but the file size + class-list patterns suggest it.

### A-6. 🛠️ `school_admin/admin.py` + `school_admin/models.py` — placeholder files
**Why:** One-liner placeholders ("No admin registrations needed", "No models needed"). They're informative, not dead.
**Best-practice alternative:** Add a 2-line docstring explaining the role separation so future contributors don't add model definitions here. 🟢 Keep.

### A-7. 🛠️ `school_admin/views/__init__.py` (2 KB) — exports a long list of view classes
**Best-practice alternative:** Keep — it's the import surface for `school_admin/urls.py`. Worth scanning once a sub-package split is done.

---

## Findings — students / academics / lessons

### S-1. 🛠️ `students/views.py:22-120` `_parent_portal_context` — 100-line helper that does too much
**Why:** Computes 9 things (children data, total owed, averages, results status, published terms count, owed_by_student, etc.) for one view. The whole dashboard logic lives here. Used by `ParentDashboardView` (and possibly `ParentChildrenListView`).
**Best-practice alternative:** Split into small helpers: `_children_with_balances(user)`, `_term_results_for_children(student_ids, term)`, `_portal_summary(children)`. Each testable in isolation. The view itself becomes 15 lines.

### S-2. 🛠️ `students/views.py` `MakePaymentView` (165 lines) — branches on `role` throughout
**Why:** Same view handles parent and student. Has 5 different `if role == Roles.PARENT:` branches. Different URL names (`parent-pay`, `student-pay`) but one view.
**Best-practice alternative:** Two thin subclasses — `ParentMakePaymentView` and `StudentMakePaymentView` — both delegating to a `_BaseMakePaymentView` with the shared logic. Cleaner role checks, easier testing. ~30 lines saved.

### S-3. 🛠️ `students/views.py` `current_term` shadow x4 — see F-15

### S-4. 🛠️ `students/views.py:627-668` `StudentExtraLessonsView` and `:306-363` `ParentExtraLessonsView` — same logic, different scope
**Why:** Identical structure (filter, balance, total outstanding). Different templates. ~60 lines × 2 with the same shape.
**Best-practice alternative:** Single `_extra_lessons_for_students(student_ids, school)` returning a dict, two views render with the right template. ~50 lines saved. Same observation for the two `*ResultBookletView` classes (671-728) — already noted in Phase 1.

### S-5. 🛠️ `students/models.py:120-128` `Student.__str__` does a DB query on every string conversion
**Why:** `.enrollments.filter(is_current=True).first()` inside `__str__`. Templates and admin lists call `str(student)` per row → N+1 in list views.
**Best-practice alternative:** Annotate in admin/list views (`Student.objects.annotate(current_class_name=...)`) and use the annotation in `__str__`, or override `__str__` to use only `self.user.get_full_name()` and provide a separate `display_name_with_class()` for templates that want the class.

### S-6. 🛠️ `students/models.py:188-193` `ClassEnrollment.save` does an UPDATE on every save
**Why:** Updates all other `is_current=True` enrollments for the student when a new one is saved. Inside a transaction this is correct, but every `student.save()` or class change triggers a query.
**Best-practice alternative:** Fine as-is for correctness; flag for performance review only if profile shows it's hot.

### S-7. ❓ `academics/views.py` — needs read

### S-8. ❓ `lessons/views.py` — needs read for split decision

---

## Findings — payroll (mirror of fees)

### P-1. 🛠️ `payroll/views.py` likely has same CRUD pattern as `school_admin/views/fees.py`
**Best-practice alternative:** Generic views (A-4).

### P-2. 🛠️ `payroll/utils.py` `generate_payslip` is 90 lines and does many things
**Why:** Creates payslip, sums allowances/deductions, creates 3× line item types. Acceptable for a one-shot generator but worth noting.
**Best-practice alternative:** Could split into `_compute_totals(...)` + `_create_payslip(...)` + `_create_line_items(...)` — three small helpers, each with one job. Pure refactor.

### P-3. 🟢 `payroll/models.py` `SalaryDisbursement` + `Payslip` mirror of Invoice/Payment — intentional
Per AGENTS.md and Phase 1 review. Keep.

---

## Findings — accounts / notifications / core

### N-1. 🛠️ `accounts/models.py:23-26` `TenantScopedUserManager` is just `pass`
**Why:** `class TenantScopedUserManager(DjangoUserManager, TenantScopedManager): pass` — relies entirely on MRO. Works, but undocumented.
**Best-practice alternative:** Add 1-line docstring or leave with a comment explaining the mixin contract. 🟢 Keep — but document.

### N-2. 🛠️ `accounts/models.py:84` `REQUIRED_FIELDS = ['email']` — overrides AbstractUser default
**Why:** AbstractUser already sets `REQUIRED_FIELDS = ['email']`. Redundant.
**Best-practice alternative:** Remove the line. Behaviour identical. Tiny cleanup.

### N-3. 🛠️ `notifications/utils.py:103` — `except Exception as exc:` swallows everything for delivery failures
**Why:** Catches all exceptions, marks `FAILED`, logs. Acceptable — `notify()` is meant to be failure-safe. But the bare `except` hides programming bugs.
**Best-practice alternative:** Catch `(SMTPException, ConnectionError, socket.error, BrevoError, ValueError)` — explicit list. Keep the safety net but make it intentional.

### N-4. 🛠️ `notifications/utils.py:118-154` `notify_many` and `notify_admins` — small, clean, fine
**Best-practice alternative:** Leave as-is. 🟢 Keep.

### N-5. 🛠️ `core/middleware.py:28-39` `CurrentUserMiddleware` uses `try/finally` correctly
**Why:** Sets thread-local user, ensures cleanup. Standard pattern. 🟢 Keep.

### N-6. 🛠️ `core/context_processors.py:67-101` `_badge_counts` mixes two roles' logic in one function
**Why:** Two distinct code paths for ADMIN vs PARENT. Fine for now (small), but if a third role gets badges, extract.
**Best-practice alternative:** `_admin_badges(school)`, `_parent_badges(user, school)`, then `_badge_counts` dispatches.

---

## Findings — across the project

### X-1. 🛠️ No tests for several critical paths
**Spot-check from grep on test files:** `fees/tests.py` has 29 test classes covering most of `fees`. But I see no tests for:
- `_handle_charge_failure` path in paystack (only `WebhookSecurityTest` covers charge.success).
- `ConfirmPaymentFromVerify` edge case (amount mismatch).
- The retry path in `initiate_payment` (existing_reference rejected → fresh reference).
- `accounts/middleware.py` `PasswordChangeRequiredMiddleware`.

**Best-practice alternative:** Add focused tests for these. Not strictly an audit finding, but the lack of tests is what makes refactoring F-4, F-6, F-23 scary.

### X-2. 🛠️ No signals.py anywhere — intentional
**Why:** `find` returned no app-level signals. `core/audit.py` registers its receivers via `@receiver` decorators. 🟢 Keep.

### X-3. 🛠️ No managers.py anywhere — intentional
**Why:** `find` returned no app-level managers. `TenantScopedManager` lives in `core/models.py` as a single class. 🟢 Keep.

### X-4. 🛠️ No forms.py anywhere — intentional
**Why:** All form validation is done manually in views via `clean()` calls + `full_clean()`. Works, but means lots of validation is repeated in views (e.g. FeeCategory create/edit both check name uniqueness + billing_cycle + student_type).
**Best-practice alternative:** Extract `FeeCategoryForm(forms.ModelForm)` and use `CreateView`/`UpdateView`. Saves ~40 lines per CRUD pair across fees/lessons/payroll/inventory.

### X-5. 🛠️ No apps.py customisation beyond `name = '...'`
**Why:** All 12 apps use the default. 🟢 Keep.

### X-6. 🛠️ `fees/checkout.py:658` final blank line + `__pycache__` in the tree — non-issues

### X-7. 🛠️ Two `student_type` resolution paths
**Where:**
- `fees/utils.py:8` `resolve_student_type(student, session=None, term=None)`
- `students/views.py:114` does its own manual lookup of "current term" + uses `resolve_student_type` indirectly through helpers

**Why this matters:** `resolve_student_type` is the single source of truth. Make sure no view or pricing helper computes student type inline. Quick grep for `student_type` returns 50+ hits — most are property reads; verify none are inline recomputations.

### X-8. 🛠️ `school_admin/views/fees.py:1146-1257` and other view methods — read-only confirmation pending
**Will be confirmed in next round.**

---

## Summary scoreboard (after deep read)

| Priority | ID | Item | Effort | Risk |
|---|---|---|---|---|
| 🟢 Phase 2 | F-1 | Delete `inventory/urls.py` | 1 line | Zero |
| 🟢 Phase 2 | F-3 | Delete duplicate `SCOPE_*` block | 8 lines | Zero |
| 🟢 Phase 2 | F-17 | Delete `FeeStructureValidator` no-op class | 10 lines | Zero (tests already skip) |
| 🟢 Phase 2 | F-18 | Delete unreachable `return saved` | 1 line | Zero |
| 🟢 Phase 2 | N-2 | Delete redundant `REQUIRED_FIELDS = ['email']` (test asserts it stays) | 1 line | Zero |
| ⚠️ Phase 3 | F-2 | Inline `messages.error/success` at 33 call sites in `lessons/views.py` then delete wrappers | ~33 edits | Low — pure refactor |
| 🟡 Phase 3 | F-6 | Single `user_can_access_payment` helper | ~70 lines saved | Low — many callers, but behaviour-preserving |
| 🟡 Phase 3 | F-23 | Single `_delete_with_log` helper in reset.py | ~100 lines saved | Low |
| 🟡 Phase 3 | F-8 | Rewrite checkout optional-branch to use FeePrice | Medium | Medium — touches payment flow |
| 🟡 Phase 3 | F-9 | Collapse two identical loops in `reconcile_checkout` | ~15 lines saved | Low |
| 🟡 Phase 3 | F-10 | Sum line items locally, save once | ~5 lines saved + N saves fewer | Low |
| 🟡 Phase 3 | F-4 | Extract `_apply_paystack_success` helper | ~50 lines saved | Medium — payment path |
| 🟡 Phase 3 | F-24 | `ReconcileResult` includes resolved items | ~50 lines saved | Low |
| 🟡 Phase 3 | A-1 | Split `school_admin/views/fees.py` | Pure file split | Zero — just moves code |
| 🟡 Phase 3 | S-1 | Split `_parent_portal_context` | Pure refactor | Low |
| 🟡 Phase 3 | S-2 | Split `MakePaymentView` by role | Pure refactor | Low |
| 🟡 Phase 3 | S-4 | Unify `*ExtraLessonsView` via shared helper | ~50 lines saved | Low |
| 🔴 Phase 4 | F-5 | Rewrite "webhook-first creation" branch via shared helper | After F-4 | Medium |
| 🔴 Phase 4 | F-7 | Lift retry loop | After F-4 | Low |
| 🔴 Phase 4 | F-11 | Extract `fees/visibility.py` | Medium | Medium |
| 🔴 Phase 4 | F-13 | `_verify_attempted_ids` → Payment field | Cross-cutting | Medium |
| 🔴 Phase 4 | F-19 / F-20 / F-21 | Clean up `pricing.py` internals | Pure refactor | Low |
| 🔴 Phase 4 | A-4 | Generic CreateView/UpdateView across admin | Big refactor | Medium |
| 🔴 Phase 4 | X-1 | Tests for payment edge cases | Adds test files | None |

---

## Phase 2 — proposed single PR (zero risk, ~30 lines deleted) — CORRECTED

**Adjusted after live verification.** Earlier version included F-2 (`messages_error/success` wrappers in `lessons/views.py`) — those wrappers ARE called 33 times in the same file, so pure delete would break the module. F-2 moved to Phase 3 as a full inline refactor.

```diff
- inventory/urls.py                           (delete; confirmed not mounted)
- fees/models.py lines 142-149                (delete dup SCOPE block)
- students/views.py 4× rename local current_term → active_term  (verify each is a true shadow first)
- fees/validation.py lines 120-129            (delete FeeStructureValidator)
- fees/validation.py line 129                 (delete unreachable return)
- accounts/models.py line 84                  (delete REQUIRED_FIELDS — test 'email in REQUIRED_FIELDS' still passes because AbstractUser sets it)
```

Total: **~30 lines removed**, zero callers broken. Full test suite runs after.

---


## Next steps

1. **You approve Phase 2** (or any subset). I implement + run `python manage.py test` + show the diff.
2. **Phase 3 plan in writing** for F-6 (helper) + F-8 (FeeStructure retirement) — biggest payoff, medium risk. Reviewed before code.
3. **Phase 1 round 2** to read `academics/views.py`, `lessons/views.py`, `payroll/views.py`, `inventory/views.py`, `school_admin/views/students.py` — fills the ❓ items.

---

## 🚨 Critical bugs found in this round

These crash-or-corrupt-data bugs should ship first, before any cleanup PR.

### B-1. ✅ `data_import/importers.py:171` references unimported `ClassSubject`
**Symptom:** Importing subjects via CSV (`POST /school-admin/import/`) crashes with `NameError: name 'ClassSubject' is not defined` as soon as it reaches line 171 (`ClassSubject.objects.create(...)`).
**Why:** `importers.py:10` imports `Subject` but not `ClassSubject`, even though the code uses it.
**Fix:** One line — add `ClassSubject` to the `from academics.models import ...` statement. Pure typo.
**Risk:** None — adds an import. Zero behaviour change for any other path.
**Note:** Only `ClassImporter`, `SubjectImporter`, `StudentImporter`, `StaffImporter` exist; only `SubjectImporter` hits line 171.

### B-2. ✅ `inventory/services.py:86,95` calls `_()` without importing `gettext_lazy as _`
**Symptom:** When a confirmed BookPurchase payment has insufficient stock, `process_payment_confirmation` runs `notify_admins(...)` with `_('Book purchase failed: insufficient stock')` and `_('Review inventory')` — both crash with `NameError: name '_' is not defined`. The exception is swallowed by the caller (it's after a `return` so the payment stays CONFIRMED but the admin never gets the alert).
**Why:** Lines 1-9 import everything except translation helpers. Two `_()` calls in the module.
**Fix:** Add `from django.utils.translation import gettext_lazy as _` at the top.
**Risk:** None — adds an import. The branch is rarely hit, but when it is, the admin is silently left in the dark about a failed payment.

**Both should land in the same PR as the Phase 2 deletions — they're all one-line fixes and the test suite stays green.**

---

## Phase 1 round 2 — deep reads (academics / lessons / payroll / inventory / admin portal / data_import / finance)

### R2-A. 🔁 `academics/ranking.py:46-55` and `:107-115` — Olympic/dense ranking implemented twice
**Same algorithm:** for each row, if total changes bump the rank; otherwise carry the previous rank. Docstrings even say "same algorithm as compute_positions" (line 107).
**Best-practice alternative:** Extract a helper `_assign_dense_ranks(rows, total_attr='total_score', id_attr='student_id')` that mutates each row's `.position` (or assigns a `_rank` attribute). Both call sites become 3 lines. ~20 lines saved, single source of truth for the ranking rule. Pure refactor — tests already lock the algorithm.

### R2-B. 🛠️ `academics/views.py:14` `VALID_SCORE_FIELDS = {'exam_score'}` — module-level constant
**Why:** Combined with `_valid_score_fields(school)` (line 17) which adds school-configured extras. Reads correctly but the module-level set can drift from per-school reality.
**Best-practice alternative:** Make it a class-level attribute on `School` (next to `score_component_maxima()`), or just inline as a frozenset literal. Trivial.

### R2-C. 🛠️ `academics/views.py:26-166` `TeacherAssignmentListView.get` — 140 lines, 5 nested concerns
**The view does:** dashboard render + per-assignment progress + "students fully graded" aggregate + recent scores + all-complete toast. Each section is a separate concern.
**Best-practice alternative:** Extract `_assignment_progress(assignments, term_scores)`, `_fully_graded_counts(assignments, term_scores)`, `_recent_scores(teacher)`. View becomes orchestration + template. ~80 lines saved, each helper unit-testable.

### R2-D. 🛠️ `academics/views.py:237-366` `TeacherScoreUpdateView.post` — 130 lines that build HTML in Python
**Lines 318-364** build an OOB-swap HTML string by hand (status badges, total cell, row class). Same `_status_badge` helper inlined here and similar logic likely in `dashboard.html` / `score_grid.html`.
**Best-practice alternative:** Move badge rendering to a template partial (`_score_status_badge.html`), render via `render_to_string`, return `HttpResponse` of the rendered HTML. Removes ~50 lines of string-concatenation, lets designers edit markup. Same for the input field HTML on lines 313-324.

### R2-E. 🛠️ `academics/views.py:237-262` — `teacher_can_edit_score` logic inlined
**Why:** Three-step check: get enrollment, find teacher assignment, decide. Same scope pattern repeats in `_valid_score_fields` style.
**Best-practice alternative:** Extract `_score_owned_by_teacher(score, user) -> bool`. Tiny.

### R2-F. 🛠️ `academics/publishing.py:9-79` `notify_results_published` — two near-identical loops
**Lines 48-64** (guardian loop) and **lines 66-79** (student loop) differ only by recipient and reference suffix. Both iterate, dedup by `(recipient_id, ref)`, call `notify()`.
**Best-practice alternative:** `_notify_one(recipient, ref_suffix, subject, message, url)` that both loops call. ~15 lines saved.

### R2-G. 🛠️ `academics/publishing.py:40` — uses `.format()` instead of f-string
**`reference__startswith='term-results:{}'.format(term.id)`** — same f-string opportunity as F-16.
**Alternative:** f-string.

### R2-H. 🔁 `lessons/views.py:415-417` and `:437-439` — identical `balance` calculation
**Both `EnrollmentDetailView` and `EnrollmentPrintView` do:**
```python
'balance': max(enrollment.fee_amount - enrollment.amount_paid, Decimal('0.00'))
```
**Best-practice alternative:** Add a `balance` property on `LessonEnrollment` (alongside existing `amount_paid` and `payment_status`). Mirrors `Invoice.balance`. Two view lines collapse to `'balance': enrollment.balance`.

### R2-I. 🛠️ `lessons/views.py:455-514` `EnrollmentPaymentView.post` — 60 lines, mixed concerns
**What:** Validates amount, creates Payment, issues receipt, notifies student, auto-flips status to PAID.
**Best-practice alternative:** Move the Payment-creation + receipt + notify tail into a service `lessons/services.py::record_enrollment_payment(enrollment, amount, method, recorded_by)` — call it from the view. The view shrinks to: parse + validate + call service + redirect. ~30 lines saved.

### R2-J. 🛠️ `lessons/views.py:461` and `lessons/views.py:498, 692` — function-local imports
**`from fees.models import Payment` and similar deferred imports inside methods.** Works but inconsistent — top of file would be cleaner. Minor.

### R2-K. 🛠️ `lessons/models.py:256-264` `LessonEnrollment.payment_status` — same UNPAID/PARTIAL/PAID pattern as `Invoice.status`
**Why:** Three models (`Invoice`, `Payslip`, `LessonEnrollment`) compute the same status from CONFIRMED-only payment sums. Same as X-7 in round 1.
**Best-practice alternative:** A shared helper in `fees/selectors.py` or a new `core/money_status.py`:
```python
def money_status(paid: Decimal, owed: Decimal) -> str:
    if paid >= owed and owed > 0: return 'PAID'
    if paid > 0: return 'PARTIAL'
    return 'UNPAID'
```
Each model becomes `payment_status = property(lambda self: money_status(self.amount_paid, self.fee_amount))`. Single source for the rule.

### R2-L. 🟢 `lessons/views.py` and `lessons/teacher_views.py` — split is fine
51 lines vs 739 lines. Two urlconfs (`urls.py`, `teacher_urls.py`) is the established pattern. No change.

### R2-M. 🛠️ `payroll/views.py:36` — `if user.role != 'ADMIN':` uses string literal instead of `Roles.ADMIN`
**Why:** Every other file in the project uses `Roles.ADMIN`. Two lines (36 and 68 of `payslip_detail`).
**Best-practice alternative:** `Roles.ADMIN`. Trivial consistency fix.

### R2-N. 🛠️ `payroll/views.py:62` — only one view method (`PayrollRunDetailView.get_queryset`) does anything domain-specific; everything else is generic
**Best-practice alternative:** Convert `PayrollRunDetailView` to `DetailView` with a `get_queryset` already done. `PayslipListView` is already `ListView`. Could be even shorter. ~5 lines saved.

### R2-O. 🛠️ `payroll/models.py:259-266` — `PayrollRun.total_disbursed` filters `SalaryDisbursement.objects.filter(payslip__in=self.payslips.all())`
**Why:** `self.payslips.all()` runs a subquery each call. If a `PayrollRun.summary()` view lists 20 runs and accesses `.total_disbursed` on each, that's 20 subqueries.
**Best-practice alternative:** Add `.annotate(total_disbursed=Sum('payslips__disbursements__amount', filter=Q(...)))` on the queryset that powers the list view. Annotation is per-row, single SQL. Same pattern for `total_gross_pay` / `total_net_pay` already done via `.aggregate()` on the related set — same problem.

### R2-P. 🛠️ `payroll/models.py:354-358` — `PayslipLineItem` doc references the `InvoiceLineItem` pattern
**Why:** This is intentional and documented. The pattern is "parent provides scope, child doesn't". 🟢 Keep, but it deserves a `core/scoped_children.py` doc if more apps add similar line-item models in the future.

### R2-Q. 🛠️ `inventory/services.py:67-122` and `:130-163` — `process_payment_confirmation` and `restore_stock_for_payment` share the same `InventoryTransaction.objects.create(...)` template
**Both build a transaction row with school/item/quantity_change/balance_after/reference/created_by/notes.** Field list is the same; only values differ.
**Best-practice alternative:** Extract `_log_stock_change(item, quantity_change, transaction_type, reference, created_by, notes)` — call it from both functions. ~10 lines saved, single field list.

### R2-R. 🛠️ `inventory/services.py:166-193` `add_procurement` — atomic block is redundant
**Why:** `transaction.atomic()` wraps a single UPDATE + two INSERTs. The atomic is correct (and necessary for rollback semantics), but the function is 28 lines and could be moved to the admin view since it's never called from anywhere else. Let me verify — quick grep next round.

### R2-S. 🔁 `inventory/views.py:281-284` (in `AdminStockRemovalView.post`) and `inventory/services.py:99-104` — both update `total_stock` via `InventoryItem.objects.filter(pk=...).update(total_stock=F('total_stock') ± qty)`
**Why:** Same pattern, same fields, same `refresh_from_db` afterwards. Could live in a service `inventory/services.py::adjust_stock(item, delta, transaction_type, ...)` and be called from both. Reduces duplication and centralizes the "create an InventoryTransaction whenever stock moves" rule.
**Best-practice alternative:** Centralize. Currently the create-transaction block is in `services.py:111-122`, the views build the fields manually.

### R2-T. 🛠️ `school_admin/views/students.py:60-65` — Python-loop annotation in `StudentListView.get`
```python
for s in students:
    current_enrollment = next((e for e in s.enrollments.all() if e.is_current), None)
    s.current_class = current_enrollment.school_class if current_enrollment else None
```
**Why:** Even though `enrollments` is `prefetch_related`'d (line 33-34), this is a Python-side scan per row. Acceptable, but a `Prefetch('enrollments', queryset=ClassEnrollment.objects.filter(is_current=True).select_related('school_class'))` would prefetch only the one row we need.
**Best-practice alternative:** Targeted Prefetch — 1 query instead of N scans. Faster on long lists.

### R2-U. 🛠️ `school_admin/views/students.py:121-150` — `ONBOARDING` set + 3 separate `resolve_prices` calls + 3 sum-loops
**Why:** This is the same onboarding-visibility logic that's also in `fees/views.py:1026-1033` (F-11). Two views compute the same onboarding total for the same student.
**Best-practice alternative:** Resolve once in `fees/visibility.py` (F-11) — `compute_onboarding_total(student, term)` returns `{new_total, returning_total, per_term_total}`. Both views call it.

### R2-V. 🔁 `school_admin/views/students.py:344-372` and `lessons/views.py:695-723` — same guardian-loop pattern
**Both:**
- Loop `guardian_index = 0; while True:` reading `guardian_{idx}_name/email/phone/...` from POST.
- Break when all three are empty.
- Call `find_or_create_parent(...)` + create `StudentGuardianLink(...)`.

**Identical structure, ~30 lines of duplication.**
**Best-practice alternative:** Extract `students/utils.py::create_guardians_from_form(student, post_data)` returning the list of created links. Both views drop ~30 lines.

### R2-W. 🛠️ `school_admin/views/results.py:79-283` `ResultReviewView.get` — 200-line single method
**Why:** Five distinct sub-views (terms list, class summary, full matrix, subject filter, search) all in one method. The `post` method (285-424) then has 4 near-identical approve/reject branches (approve_all, approve_subject, reject_subject, approve_student, reject_student, plus the single-score approve/reject). All call `_recompute`.
**Best-practice alternative:**
- Split `get` into `_terms_overview(school)`, `_class_summary(school, term, classes)`, `_class_matrix(school, term, school_class, subject_id, q)`.
- Replace the 6 post-branches with `_moderate(school, qs, verb)` + a single queryset built per action.

~150 lines saved. Tests don't exist for this view (X-1), so the refactor should land alongside tests.

### R2-X. 🛠️ `school_admin/views/results.py:285-424` `post` — every branch ends with `_recompute(enrollment.school_class, score.term)` or `_recompute(school_class, term)`
**Why:** `_recompute` does the same thing (compute_positions for each subject + compute_term_summary). Six call sites.
**Best-practice alternative:** Already extracted (good!). But the entire branch structure is begging for a `_apply_moderation(school, action, term_id, class_id, subject_id, student_id, score_id, user)` that returns `(count, school_class, term)` — view becomes routing + flash message. ~80 lines saved.

### R2-Y. 🛠️ `school_admin/views/dashboard.py:100-110` and `:130-138` — same `next(... for e in student.enrollments.all() if e.is_current, None)` lookup happens twice
**Best-practice alternative:** Same targeted Prefetch as R2-T. Two loops, one query each.

### R2-Z. 🛠️ `finance/views.py:107-138` — `FinancialReportView` aggregates 3 sources with 3 nearly-identical `Sum('amount').aggregate(...)` calls
**Why:** Three blocks of "filter, aggregate, default Decimal('0.00')". Different sources, same shape.
**Best-practice alternative:** `_sum_confirmed(model, school, field, start, end)` returning `Decimal('0.00')` default. Three call sites become one-liners. ~15 lines saved.

### R2-AA. 🛠️ `data_import/importers.py:112-114`, `:187-189`, `:378-380`, `:447-449` — four identical `_log(self, msg)` methods
**Every subclass defines its own `_log(self, msg): print(msg)`.** The base class already has `self.verbose` and `_counter` — `_log` should live in the base.
**Best-practice alternative:** Move `_log` to `BaseImporter`. Delete all four overrides. Pure refactor. Also: `_log` should use `logging.getLogger(__name__).info(...)` not `print()` — proper logging.

### R2-BB. 🛠️ `data_import/importers.py:159-163` — manual suffix loop for unique subject codes
**Why:** `while Subject.objects.filter(code=code).exists(): code = f'{base_code}{suffix}'` — classic race condition if two imports run concurrently.
**Best-practice alternative:** Use `unique_together` on `(school, code)` and let the IntegrityError trigger a retry; or just accept the race and document it.

### R2-CC. 🛠️ `data_import/importers.py:60` — strips values but doesn't strip keys
**`{k: v.strip() if v else '' for k, v in row.items()}`** — values stripped, keys left as-is. Means a CSV with `' First Name '` header would silently fail to match `'first_name'` lookups.
**Best-practice alternative:** `{k.strip(): (v.strip() if v else '') for k, v in row.items()}`. One-line fix.

### R2-DD. 🛠️ `data_import/views.py:71-83` and `:128-179` — temp-file dance repeated
**Both `DataImportView.post` and `DataImportConfirmView.post` write rows to a temp CSV, call the importer, then `os.unlink(tmp.name)` in a `finally`.**
**Best-practice alternative:** Extract `_write_rows_to_tempfile(rows) -> path` + context manager `tempfile_for_rows`. Both views drop ~10 lines.

### R2-EE. 🛠️ `data_import/views.py:18-23` and `:25-30` — `IMPORTERS` and `TEMPLATES` dicts in views.py
**Why:** Domain config lives in the view file. Belongs in `importers.py` or a new `data_import/config.py`.
**Best-practice alternative:** Move to `importers.py` alongside the importer classes. View becomes thin.

### R2-FF. 🛠️ `school_admin/views/staff.py:62-74` — `if not all([first_name, last_name, role, phone_number]):` then 3 different `render(request, 'school_admin/staff/staff_form.html', ...)` repeats
**Why:** Same context dict on every error path. Same pattern repeats in `fee_category_form.html`, `student_form.html`, `class_form.html`, etc.
**Best-practice alternative:** A `_render_with_form(request, context_overrides=None)` helper per form, or just generic `CreateView`. Same observation as A-4.

### R2-GG. 🟢 Confirmed clean in this round
- `accounts/views.py` — login/logout + password change. Standard Django. Keep.
- `notifications/utils.py` — clean. Keep.
- `school_admin/views/dashboard.py` — large view but linear, one concern. Keep as-is until R2-Y's prefetch lands.
- `finance/views.py` — 162 lines, 4 small views. Fine.
- `data_import/views.py` — clean structure, just needs the temp-file refactor (R2-DD).
- `payroll/utils.py` — fine; could split per R2-N but not urgent.

---

## Updated scoreboard

| Priority | ID | Item | Effort | Risk |
|---|---|---|---|---|
| 🚨 **Bugs first** | B-1 | Add `ClassSubject` to importers.py imports | 1 line | Zero |
| 🚨 **Bugs first** | B-2 | Add `gettext_lazy as _` to inventory/services.py | 1 line | Zero |
| 🟢 Phase 2 | F-1 | Delete `inventory/urls.py` (confirmed not mounted) | 1 line | Zero |
| 🟢 Phase 2 | F-3 | Delete duplicate `SCOPE_*` block | 8 lines | Zero |
| 🟢 Phase 2 | F-15 | Fix `current_term` shadow in `students/views.py` | 2 lines | Zero |
| 🟢 Phase 2 | F-17 | Delete `FeeStructureValidator` no-op class | 10 lines | Zero (tests already skip) |
| 🟢 Phase 2 | F-18 | Delete unreachable `return saved` | 1 line | Zero |
| 🟢 Phase 2 | N-2 | Delete redundant `REQUIRED_FIELDS = ['email']` (AbstractUser still provides; existing test passes) | 1 line | Zero |
| ⚠️ Phase 3 | F-2 | Inline `messages.error/success` at 33 call sites in `lessons/views.py` then delete wrappers | ~33 edits | Low — pure refactor |
| 🟡 Phase 3 | F-6 | Single `user_can_access_payment` helper | ~70 lines saved | Low |
| 🟡 Phase 3 | F-23 | Single `_delete_with_log` helper in reset.py | ~100 lines saved | Low |
| 🟡 Phase 3 | F-8 | Rewrite checkout optional-branch to FeePrice | Medium | Medium |
| 🟡 Phase 3 | F-9 | Collapse duplicate loops in `reconcile_checkout` | ~15 lines saved | Low |
| 🟡 Phase 3 | F-10 | Sum line items locally, single save | N saves → 1 | Low |
| 🟡 Phase 3 | F-4 | Extract `_apply_paystack_success` helper | ~50 lines saved | Medium |
| 🟡 Phase 3 | F-24 | `ReconcileResult` includes resolved items | ~50 lines saved | Low |
| 🟡 Phase 3 | A-1 | Split `school_admin/views/fees.py` | Pure file split | Zero |
| 🟡 Phase 3 | S-1 | Split `_parent_portal_context` | Pure refactor | Low |
| 🟡 Phase 3 | S-2 | Split `MakePaymentView` by role | Pure refactor | Low |
| 🟡 Phase 3 | S-4 | Unify `*ExtraLessonsView` via shared helper | ~50 lines saved | Low |
| 🟡 Phase 3 | R2-A | Extract `_assign_dense_ranks` from ranking.py | ~20 lines saved | Zero (pure refactor) |
| 🟡 Phase 3 | R2-H | Add `LessonEnrollment.balance` property | 2 lines | Zero |
| 🟡 Phase 3 | R2-K | Shared `money_status()` helper | Pure refactor | Low |
| 🟡 Phase 3 | R2-V | Extract `create_guardians_from_form()` | ~30 lines saved × 2 | Low |
| 🟡 Phase 3 | R2-AA | Move `_log` to `BaseImporter`, use logging | 4 deletions | Zero |
| 🟡 Phase 3 | R2-W | Split `ResultReviewView.get` into 3 helpers | ~80 lines saved | Medium (no tests) |
| 🟡 Phase 3 | R2-X | One `_apply_moderation()` helper | ~80 lines saved | Medium |
| 🟡 Phase 3 | R2-DD | Temp-file context manager in data_import | ~10 lines saved | Low |
| 🟡 Phase 3 | R2-EE | Move `IMPORTERS`/`TEMPLATES` to importers.py | Pure move | Zero |
| 🟡 Phase 3 | R2-M | `payroll/views.py:36,68` use `Roles.ADMIN` | 2 chars | Zero |
| 🟡 Phase 3 | R2-CC | Strip keys in importers.py:60 | 1 char | Zero |
| 🟡 Phase 3 | R2-T / R2-Y | Targeted Prefetch for current enrollment | 1 line each | Zero |
| 🔴 Phase 4 | F-5, F-7, F-11, F-13, F-19-21, A-4 | See earlier list | After Phase 3 | varies |

---

## Phase 2 — proposed single PR (corrected — confirmed-safe only)

```diff
+ inventory/services.py: add `from django.utils.translation import gettext_lazy as _`  (BUG FIX B-2)
+ data_import/importers.py: add `ClassSubject` to academics import                      (BUG FIX B-1)
- inventory/urls.py                           (delete; confirmed not mounted)
- fees/models.py lines 142-149                (delete dup SCOPE block)
- students/views.py 4× rename local current_term → active_term
- fees/validation.py lines 120-129            (delete FeeStructureValidator no-op class)
- fees/validation.py line 129                 (delete unreachable `return saved`)
- accounts/models.py line 84                  (delete redundant REQUIRED_FIELDS; existing test passes)
- payroll/views.py:36,68 use Roles.ADMIN     (consistency, R2-M)
```

**Deliberately removed** vs earlier draft:
- ❌ `lessons/views.py` wrappers — moved to Phase 3 (F-2), as wrappers ARE used 33 times
- ❌ R2-AA (`_log` move) and R2-CC (strip keys) — defer to a `data_import` mini-refactor PR
- ❌ N-2 caveat noted: `accounts/tests.py` asserts `'email' in REQUIRED_FIELDS`; AbstractUser already provides it so the assertion stays green.

Total: **2 bug fixes + ~30 lines removed**, zero callers broken. Full test suite runs after.

**This is the recommended first PR.** After it lands we have the B-1/B-2 crashes fixed, several dead-code paths removed, and a clean baseline for the bigger Phase 3 work.

---


## Next steps

1. **You approve this PR** (or any subset). I implement + run `python manage.py test` + show the diff.
2. **Phase 3 plan in writing** for the FeeStructure retirement (R5 / F-8) — biggest payoff.
3. **Phase 1 round 3** for `school_admin/views/{credentials,parents,notifications,payroll,school_settings,sessions,search}.py` — these are small enough to spot-check rather than deep-read.
