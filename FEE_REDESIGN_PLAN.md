# Fee Management & Payment Redesign — Implementation Plan

> **Date:** 2026-09-16  
> **Scope:** `fees/`, `school_admin/views/invoices.py`, `school_admin/views/fee_pricing.py`, 
> `school_admin/templates/school_admin/_student_detail_fees_tab.html`, 
> `school_admin/templates/school_admin/invoice_detail.html`, related test files

---

## 1. Executive Summary

The current fee system uses a **category → price** two-layer abstraction where `FeeCategory` 
is a grouping concept (Tuition, Registration, Uniforms, PTA) and `FeePrice` holds the 
amount per category+scope+term. While functionally correct, this creates confusion for admins:

- Pricing is managed at the *category* level, but admins think in terms of "what items does 
  a student owe"
- The payment recording UI requires understanding scope semantics (Class Total vs Invoice vs 
  Free-form) and checkbox-level item selection
- Overpayment is blocked at the view level rather than handled gracefully
- Invoice line items display category names rather than the actual item names admins set

The redesign introduces a **direct itemized model** where each `FeePrice` becomes a 
self-contained chargeable item with its own name and price, replaces the complex category-grouped 
UI with a simple itemized list, and introduces proper overpayment capping.

---

## 2. Current Architecture Analysis

### 2.1 Model Relationships

```
FeeCategory (1) ──→ (N) FeePrice          # pricing per scope+term
FeeCategory (1) ──→ (N) FeePriceOverride   # per-student overrides
FeeCategory (1) ──→ (N) InvoiceLineItem    # what's on an invoice
FeePrice     (FK) → FeeCategory            # which category this price is for
Invoice      (1) ──→ (N) InvoiceLineItem   # line items on an invoice
Invoice      (1) ──→ (N) Payment           # payments against this invoice
Payment      (1) ──→ (N) PaymentLineItem   # what a payment covers
```

### 2.2 Pricing Resolution Chain

```
resolve_prices(school, class, term, student_type, student, session)
  → _resolve_from_feeprice()        # scope precedence: CLASS > LEVEL(Section) > SCHOOL_WIDE
  → filter by is_compulsory=True    # only compulsory categories
  → filter student_type: Q(student_type='ALL') | Q(student_type=T)   # T = NEW or RETURNING
  → dedup by category_id (most-specific scope wins)
  → filter one-time billing (skip if already billed)
```

### 2.3 Student-Type Sub-Scoping — Two Existing Defects

The model **already** supports one price row per (scope, class/level, term, category, **student_type**) 
via `unique_together` — a single item can have a `NEW` row, a `RETURNING` row, and an `ALL` row, 
each with its own amount. But the *resolution logic* does not reliably honor this sub-scoping:

**Defect A — Nondeterministic tie between type-specific and `ALL` rows within the same scope.**
In `_resolve_from_feeprice()`:

```python
explicit.sort(key=lambda p: (scope_precedence.get(p.scope, 99), p.category_id))  # line 89
deduped_explicit = []
seen_cats = set()
for fp in explicit:
    if fp.category_id in seen_cats:
        continue
    seen_cats.add(fp.category_id)
    deduped_explicit.append(fp)
```

Both a `(CLASS, NEW, Tuition, 90000)` row and a `(CLASS, ALL, Tuition, 80000)` row pass the
`student_type` filter for a NEW student, get the *same* sort key `(0, tuition_cat_id)`, and the
dedup keeps whichever the DB happened to return first. **A NEW student may be charged the ALL 
price instead of their NEW price.** The fix is a deterministic sub-scope precedence inside the 
sort key (see §4.2.2).

**Defect B — Generation and display use different type rules.**
`generation.py` pulls only `category__is_compulsory=True` rows via `resolve_prices`, while the
portal line-items UI additionally applies the **name-based** filtering in `visibility.py`
(`RETURNING_HIDDEN_CATEGORIES = {'Registration Form', 'PTA', ...}`). Consequence: a RETURNING
student can be **billed** for a compulsory item that the portal hides. Type applicability must
live in one place — the resolver — not in hardcoded name sets.

**Planned fix for both:** make student-type applicability an **explicit per-item dimension**
(deactivate or omit the `RETURNING` row instead of hiding it by name), and make the resolver the
single source of truth used by generation, checkout, and portals alike. `visibility.py` name-set
logic is retired as legacy (<code>visibility.py</code>).

### 2.4 Invoice Generation Flow

```
generate_invoice_for_student(student, term)
  → find enrollment (ClassEnrollment, is_current=True)
  → resolve_student_type() → 'NEW' or 'RETURNING'
  → effective_fee_structures() → resolve_prices() 
  → create InvoiceLineItem per category (category FK, amount)
  → sum amounts → Invoice.total_amount
```

### 2.5 Admin Payment Recording

```
StudentRecordPaymentView.post(student_pk)
  → parse selected_line_items[] (source:price:id or source:invoice:id)
  → resolve each to payment_items[]
  → create Payment (invoice-linked or invoice-less)
  → create PaymentLineItem per selected item
  → _auto_flip_student_type() if Registration Form paid
  → issue_receipt(), notify()
```

### 2.6 Key Files Affected

| File | Lines | Role | Impact |
|------|-------|------|--------|
| `fees/models.py` | 677 | FeeCategory, FeePrice, Invoice, Payment, InvoiceLineItem, PaymentLineItem | Add `name` field to FeePrice; update InvoiceLineItem |
| `fees/pricing.py` | 160 | Price resolution engine | Minor: use FeePrice.name in output |
| `fees/generation.py` | 253 | Invoice generation | Use FeePrice.name as line item label |
| `fees/checkout.py` | 718 | Checkout cart assembly & reconciliation | Simplify checkout options |
| `fees/views.py` | 1132 | Payment initiation, line items API | Simplify line items API response |
| `school_admin/views/invoices.py` | 752 | Admin invoice/payment views | Overpayment handling, simplified recording |
| `school_admin/views/fee_pricing.py` | 539 | Admin fee pricing CRUD | Add name field to create/edit forms |
| `school_admin/templates/.../invoice_detail.html` | 196 | Invoice detail + payment form | Overpayment UI |
| `school_admin/templates/.../_student_detail_fees_tab.html` | 305 | Student fees tab + payment form | Full redesign |
| `school_admin/templates/.../fee_pricing_form.html` | — | Fee pricing form | Add name field |
| `school_admin/templates/.../fee_pricing_list.html` | — | Fee pricing list | Show item name |
| `fees/tests.py` | ~113 | Core fee tests | Update for name field, overpayment |
| `fees/test_pricing.py` | ~30 | Pricing resolution tests | Update for name field |
| `fees/tests_payment_management.py` | ~14 | Payment management tests | Overpayment tests |
| `fees/test_checkout.py` | ~14 | Checkout tests | Simplified flow |
| `fees/test_payment_recording.py` | ~13 | Payment recording tests | Overpayment edge cases |
| `school_admin/tests.py` | ~98 | Admin portal tests | Update payment recording tests |

---

## 3. Design Solution

### 3.1 Core Principle

**FeePrice becomes the canonical item.** Every `FeePrice` row = one chargeable item with:

| Field | Purpose |
|-------|---------|
| `name` (NEW) | Display name for this item (e.g., "Tuition Fee - JSS1", "PTA Levy") |
| `amount` (existing) | The price |
| `scope` (existing) | SCHOOL_WIDE / LEVEL / CLASS |
| `student_type` (existing) | NEW / RETURNING / ALL |
| `billing_cycle` (existing, on category) | PER_TERM / ONE_TIME |
| `category` (existing FK) | Links to FeeCategory for billing rules and visibility |

The `FeeCategory` model stays as-is — it continues to serve as the grouping mechanism for 
`billing_cycle`, `is_compulsory`, `student_type` defaults, and visibility rules. But the 
**admin-facing name** becomes `FeePrice.name`.

#### 3.1.1 Student Type is a Sub-Scoping Dimension (New vs Returning)

Every scope (CLASS, LEVEL/Section, SCHOOL_WIDE) can be **further sub-scoped by student type**.
A single item may exist as up to three price rows at the same scope — one for `NEW`, one for
`RETURNING`, one for `ALL` — each with its own amount and optionally its own name. The
sub-scoping is always **within the resolved scope**, never across scopes.

Concrete example — class `JSS1A`, current term:

| Item (`FeePrice.name`) | Scope | student_type | Amount | Applies to |
|---|---|---|---|---|
| Tuition Fee — JSS1A | CLASS (JSS1A) | `NEW` | ₦85,000 | New students in JSS1A |
| Tuition Fee — JSS1A | CLASS (JSS1A) | `RETURNING` | ₦75,000 | Returning students in JSS1A |
| Registration Form | CLASS (JSS1A) | `NEW` | ₦25,000 | New students only (one-time) |
| Uniforms | LEVEL (JSS1) | `NEW` | ₦15,000 | New students in any JSS1 class |
| PTA Levy | SCHOOL_WIDE | `ALL` | ₦10,000 | Everyone (fallback) |

Resolution for a **NEW** student in JSS1A:
`Tuition NEW 85,000` (beats the hypothetical CLASS/ALL row) + `Registration 25,000` +
`Uniforms 15,000` + `PTA 10,000` = **₦135,000**.

Resolution for a **RETURNING** student in JSS1A:
`Tuition RETURNING 75,000` + `PTA 10,000` = **₦85,000** — no Registration/Uniforms rows exist
for RETURNING, so they simply don't resolve (no hidden-by-name logic).

"Section" in the requirements maps to the existing **LEVEL** scope (grade band such as `JSS1`,
`Primary 3`). A LEVEL scope means the price applies to every class in that band; a CLASS scope
overrides it for one specific class.

### 3.2 Student-Type Sub-Scoping Resolution Rules

One canonical price per item is chosen in two stages. **Stage 1 picks the scope; Stage 2 picks
the student-type row within that scope.** Student-level `FeePriceOverride` remains supreme and
is evaluated before any price resolution.

```
For each item (category) and a student of type T ∈ {NEW, RETURNING}:

1. FeePriceOverride(student, category).amount          ← always wins if active
2. Scope precedence (same as today):
     CLASS (0)  >  LEVEL/Section (1)  >  SCHOOL_WIDE (2)
3. Student-type precedence WITHIN the winning scope:   ← NEW deterministic rule
     T-specific (0)  >  ALL (1)
4. Tiebreak: lowest pk (oldest row) — deterministic
```

Example: a NEW student in JSS1A with both a `CLASS/JSS1A/ALL/Tuition @ ₦80,000` row and a
`CLASS/JSS1A/NEW/Tuition @ ₦85,000` row resolves **₦85,000**. Scope comes first, so a
`LEVEL/NEW` row still loses to a `CLASS/ALL` row — class is the student's exact location, and
type refines *within* it.

The resolved type T comes from `resolve_student_type(student, session)` in `fees/utils.py`:

- no prior enrollment and no paid Registration Form → `NEW`
- prior enrollment or paid Registration Form → `RETURNING`

The admin can override the computed type at record time via the existing NEW/RETURNING toggle
(see §4.4.1); the override flows straight into the resolver as T.

### 3.3 Overpayment Handling

Current behavior: Admin view blocks payment when `amount > invoice.balance`.

New behavior:
- `InvoiceDetailView.post()`: accept any positive amount, cap `amount_owing` at 0
- `StudentRecordPaymentView.post()`: accept any positive amount for the selected items
- Display: `Amount Owing` = `max(0, total_payable - amount_paid)` — never negative
- The actual `Invoice.balance` property is `total_amount - amount_paid`, which may go negative 
  in the database (this is intentional — it represents overpayment/credit)

The `Payment.amount` always records the actual amount received. The display layer 
(clamp to 0 for "amount owing") is the only place that enforces the zero floor.

### 3.4 Admin Payment Interface Redesign

**Before (current):**
1. Admin selects scope (Class Total / Invoice / None)
2. HTMX loads line items for the selected scope
3. Admin ticks checkboxes for individual fee categories
4. Admin enters amount (auto-filled from checked items)
5. Admin selects method, enters optional details

**After (redesigned):**
1. Admin sees a **"Total Payable"** KPI card prominently at the top
2. A flat **itemized list** shows every applicable fee item (name + amount)
3. Each item has a checkbox (all checked by default for compulsory items)
4. Admin sees a running total as they toggle items
5. Admin enters **Amount Paid** and a **Description** (free text)
6. System auto-calculates: `Amount Paid = entered amount`, `Amount Owing = max(0, Total - Paid)`
7. Submit button: "Record Payment & Issue Receipt"

### 3.5 Invoice Detail Page Redesign

**Before:** Amount must not exceed balance (error on overpayment)  
**After:** Admin enters any positive amount. If overpayment occurs:
- Payment is recorded with the full amount
- "Amount Owing" shows ₦0.00 (capped)
- A subtle note: "₦X.XX credit applied" when payment > balance

---

## 4. Detailed Technical Changes

### 4.1 Model Changes

#### 4.1.1 Add `name` field to `FeePrice`

```python
# fees/models.py — FeePrice class
name = models.CharField(
    max_length=200,
    blank=True,
    verbose_name=_('item name'),
    help_text=_('Display name for this fee item. '
                'Leave blank to use the category name.'),
)
```

**Why blank=True:** Existing rows inherit the category name. New entries can have 
custom names like "Tuition Fee — JSS1" or "Registration Form (New Students)".

**Display logic (new property):**
```python
@property
def display_name(self):
    return self.name.strip() if self.name.strip() else self.category.name
```

**Migration:** Single `AddField` with `blank=True` — no data migration required. 
Existing rows get `name=''` and fall back to `category.name`.

#### 4.1.2 Update `InvoiceLineItem` to store item name

Add a denormalized `item_name` field to `InvoiceLineItem`:

```python
# fees/models.py — InvoiceLineItem class
item_name = models.CharField(
    max_length=200,
    blank=True,
    verbose_name=_('item name'),
    help_text=_('Denormalized item name at time of invoice generation.'),
)
```

**Why denormalize:** If an admin renames a FeePrice later, historical invoices 
should retain the original name they were generated with.

**Migration:** `AddField` with `blank=True`. Existing rows get empty string. 
Views/templates fall back to `category.name` when `item_name` is empty.

### 4.2 Pricing Resolution Changes

#### 4.2.1 `fees/pricing.py` — `resolve_prices()` output

No structural change to the resolver. Each returned `FeePrice` object already carries 
its `name` field. Callers (generation, views, templates) use `.display_name` instead 
of `.category.name`.

Update `_resolve_from_feeprice` to use `.select_related('category')` in the queryset 
to avoid N+1 (already done, but verify).

#### 4.2.2 `fees/pricing.py` — Deterministic student-type sub-scoping (Fixes Defect A)

Replace the scope-only sort and category-only dedup with a two-stage key so that, within
the matched scope, the T-specific row **always** beats the `ALL` row:

```python
scope_precedence = {
    FeePrice.SCOPE_CLASS: 0,
    FeePrice.SCOPE_LEVEL: 1,
    FeePrice.SCOPE_SCHOOL_WIDE: 2,
}
# 0 = exactly matches the student's type T, 1 = ALL fallback, 2 = other type (excluded)
type_precedence = {
    target_type: 0,          # 'NEW' for a new student / 'RETURNING' for a returning one
    'ALL': 1,
}
```

Sort key becomes `(scope_precedence, type_precedence, category_id, pk)`. Because Python's
`list.sort` is stable and the key is now total, the dedup-by-`category_id` loop retaining the
first occurrence yields the most-specific (scope, then type) row deterministically.

```python
explicit.sort(key=lambda p: (
    scope_precedence.get(p.scope, 99),
    type_precedence.get(p.student_type, 2),
    p.category_id,
    p.pk,
))
```

Clarify the `student_type` parameter semantics in the docstring:

- `'NEW'` / `'RETURNING'` → **target mode**: filter rows to `Q(student_type='ALL') | Q(student_type=T)`, 
  then apply the type precedence above. Used everywhere a specific student is involved 
  (invoice generation, checkout, portal line items, admin record-payment).
- `'ALL'` → **aggregate mode**: no student-type filter (dashboard/class-total reporting). The
  same two-stage sort still applies so the reported row is the most specific available.

#### 4.2.3 One source of truth for type applicability (Fixes Defect B / retires `visibility.py`)

Retire the name-based visibility rules. Type applicability becomes an explicit property of
each item row:

- If an item should not apply to RETURNING students, admins simply omit the `RETURNING` row
  and mark the `ALL`/`NEW` row accordingly — the resolver already excludes it (target mode
  contains no matching row), so **generation and display agree automatically**.
- `fee_pricing_list.html` shows a clear per-type column (NEW / RETURNING / ALL) per item so
  omissions are visible.
- Remove imports of `is_category_visible`, `RETURNING_HIDDEN_CATEGORIES`, `ONBOARDING_TOTAL_CATEGORIES`
  from the four call sites (`fees/views.py::student_line_items_api`, checkout extras, the 
  `total_pseudo` onboarding block, and the student detail view in `school_admin/views/students.py`).
- Keep `CHRISTMAS_FEE` first-term logic (`_is_first_term_of_session`) — it is term-scoped, not
  type-scoped; move it into the resolver or the item's effective dating so it also stays 
  consistent across generation and display.

#### 4.2.4 `fees/generation.py` — Invoice generation

Update `generate_invoice_for_student()` to populate `InvoiceLineItem.item_name`:

```python
for fs in fee_structures:
    InvoiceLineItem.objects.create(
        invoice=invoice,
        category=fs.category,
        amount=fs.amount,
        term=term,
        session=term.session,
        billing_cycle=fs.category.billing_cycle,
        item_name=fs.display_name,  # ← NEW
    )
```

Same change in `sync_class_invoices()`.

### 4.3 Overpayment Handling Changes

#### 4.3.1 `fees/models.py` — `Invoice.balance` property

Current:
```python
@property
def balance(self):
    return self.total_amount - self.amount_paid
```

**No change needed.** The property already returns a negative value on overpayment. 
The display layer (templates, API responses) applies the `max(0, ...)` clamp.

Add a new property for the clamped display value:

```python
@property
def display_balance(self):
    """Non-negative balance for display. Capped at 0 for overpayments."""
    b = self.balance
    return b if b > Decimal('0.00') else Decimal('0.00')
```

#### 4.3.2 `school_admin/views/invoices.py` — `InvoiceDetailView.post()`

**Current (lines 86-133):** Rejects `amount > invoice.balance`

**New:** Accept any positive amount. No balance cap validation:

```python
# REMOVE: if amount > invoice.balance: messages.error(...)
# The payment records the actual amount. Display layer handles the cap.
```

The payment is recorded with the full amount. The invoice `balance` may go negative. 
The template shows `display_balance` (clamped to 0) for "Amount Owing".

#### 4.3.3 `school_admin/views/invoices.py` — `StudentRecordPaymentView.post()`

**Current (line 582-586):** No explicit balance check (it accepts any amount).

**No structural change needed.** The payment amount is validated as positive but 
not capped to any balance. The overpayment is already implicitly allowed here.

#### 4.3.4 `fees/selectors.py` — `invoices_with_balance()`

The `balance_annotated` annotation may produce negative values. The template 
and views that display this should use `Greatest(balance_annotated, 0)` or 
handle the clamp in the template:

```python
from django.db.models.functions import Greatest

balance_expr = ExpressionWrapper(
    Greatest(F('total_amount') - amount_paid_expr, Value(Decimal('0.00'))),
    output_field=DecimalField(max_digits=12, decimal_places=2),
)
```

This ensures the annotated balance is never negative for list/report views.

### 4.4 Admin UI Template Changes

#### 4.4.1 `_student_detail_fees_tab.html` — Payment Recording Panel

**Key layout changes:**

```
┌─────────────────────────────────────────────────────┐
│  Record a payment                                   │
│  Type: [New] [Returning]   ◄— defaults to computed  │
│        type; admin may override (shows "override"   │
│        nudge when it differs)                       │
│                                                     │
│  ┌──────────────┐ ┌──────────┐ ┌────────────────┐   │
│  │ Total        │ │ Amount   │ │ Amount Owing   │   │
│  │ Payable      │ │ Paid     │ │ (auto-calc)    │   │
│  │ ₦135,000     │ │ ₦ 50,000 │ │ ₦85,000        │   │
│  └──────────────┘ └──────────┘ └────────────────┘   │
│                                                     │
│  ☑ Tuition Fee — JSS1A (New)     ₦ 85,000         │
│  ☑ Registration Form             ₦ 25,000         │
│  ☑ Uniforms                      ₦ 15,000         │
│  ☑ PTA Levy                      ₦ 10,000         │
│  ☐ Exam Fee (optional)           ₦ 12,000         │
│                                                     │
│  Running total: ₦135,000 (from checked items)      │
│                                                     │
│  Amount Paid: [________]                            │
│  Description: [________]                            │
│  Method:      [Cash ▼]                              │
│                                                     │
│  [Record Payment & Issue Receipt]                   │
└─────────────────────────────────────────────────────┘
```

Note the amounts are **type-aware**: switch to *Returning* and the item list re-resolves —
`Tuition Fee — JSS1A (Returning) ₦75,000`, no Registration Form/Uniforms rows, Total Payable
drops to ₦85,000. The line-items API is re-queried with the selected type as `student_type`.

**Implementation:**

1. The `student_line_items_api` endpoint accepts the existing `student_type` query param 
   (`NEW`/`RETURNING`) and returns items with `display_name` (from `FeePrice.display_name`) 
   instead of `category_name`, plus `student_type` in the metadata.

2. The HTMX partial (`student_line_items_breakdown.html`) renders the flat itemized list with 
   checkboxes. Each row shows the item name and its amount **as resolved for the selected type**
   (e.g. a NEW item name may differ from the RETURNING one for the same underlying category).

3. The existing NEW/RETURNING toggle (currently `record-payment-toggle-new` / 
   `-returning`, with the hidden `record_payment_type` input) becomes the type driver:
   - Defaults to `resolve_student_type(student, session)` at page load
   - On toggle, re-fires the HTMX request with `student_type=<selected>` so both the item list
     and `total_payable` update
   - If the selected type differs from the computed default, show a small 
     "Override from computed type" hint (prevents accidental mis-billing)

4. JavaScript computes:
   - `running_total` = sum of checked items' amounts
   - `amount_owing` = `max(0, total_payable - amount_paid)` (updates on input)
   - `amount_paid` = value in the Amount input field

5. The `total_pseudo` / "Full Package" logic for NEW students is preserved but 
   displayed as a header summary, not a pseudo-item.

6. A new HTMX endpoint (or modify existing) returns:
   ```json
   {
     "items": [...],
     "total_payable": "135000.00",
     "student_name": "John Doe",
     "class_name": "JSS1A",
     "student_type": "NEW"
   }
   ```

7. `student_line_items_api`'s `student_type` handling is simplified to forward the
   selected type straight into `resolve_prices(...)` instead of today's roundabout
   `resolver_student_type = 'ALL' if student_type == 'RETURNING' else 'NEW'` — that
   line currently **never resolves RETURNING-specific prices**, which is part of Defect A.

#### 4.4.2 `invoice_detail.html` — Overpayment Support

**Changes:**
1. Remove `max="{{ invoice.balance }}"` from the amount input
2. Remove the validation that rejects overpayment
3. Add real-time "Amount Owing" computation in JS
4. Add a credit indicator when overpayment occurs

```html
<!-- BEFORE -->
<input type="number" name="amount" step="0.01" max="{{ invoice.balance }}" required ...>

<!-- AFTER -->
<input type="number" name="amount" step="0.01" required
       min="0.01" ...>
<div id="amount-owing-display" class="text-sm text-ink-muted mt-1">
  Amount Owing: <span id="amount-owing-value">₦{{ invoice.balance|floatformat:2 }}</span>
</div>
```

JavaScript computes `amount_owing = max(0, invoice.balance - entered_amount)`.

#### 4.4.3 `fee_pricing_form.html` — Add Name Field + Per-Type Pricing

Add an "Item Name" field to the pricing form:

```html
<div>
  <label class="block text-xs font-semibold text-ink mb-1.5">Item Name</label>
  <input type="text" name="name" value="{{ selected_name|default:'' }}" 
         placeholder="e.g. Tuition Fee — JSS1 (leave blank for category name)"
         class="...">
  <p class="mt-1 text-[11px] text-ink-muted">Leave blank to use the category name.</p>
</div>
```

Add a "Student Type" field — where the item's price applies:

```html
<select name="student_type">
  <option value="ALL">All students</option>
  <option value="NEW">New students only</option>
  <option value="RETURNING">Returning students only</option>
</select>
```

Shorter path for the common "same item, different price per type" case — a checkbox
`apply_to_other_type` on create: when ticked, the view also creates (or updates) the sibling
row for the *other* student type with the same name and entered amount. Admins then edit the
amounts individually. This produces exactly the two-row layout from §3.1.1:

| Item | Scope | NEW | RETURNING |
|---|---|---|---|
| Tuition Fee | CLASS JSS1A | ₦85,000 | ₦75,000 |

Both rows share the same item `name`; only `amount` and `student_type` differ. The `unique_together`
constraint already permits both rows (student_type is part of the key), so no schema change.

**Validation note:** on Create/Edit in `fee_pricing.py`, `student_type` must be validated against
`FeeCategory.STUDENT_TYPE_CHOICES` (already done — lines 264-265 / 411-412) and the dedup check
must include `student_type` (already in the duplicate query at lines 315-325 / 463-473).

#### 4.4.4 `fee_pricing_list.html` — Show Item Name + Student Type Column

Update the pricing list table to show `display_name` (FeePrice.name or fallback 
to category.name) in the name column, and add a dedicated **Type** column so
sub-scoping omissions are obvious at a glance:

```html
<!-- BEFORE -->
<td>{{ p.category.name }}</td>

<!-- AFTER -->
<td>{{ p.display_name }}</td>
{% if p.name %}<span class="text-[10px] text-ink-muted ml-1">(custom)</span>{% endif %}
...
<td>
  {% if p.student_type == 'ALL' %}<span class="badge">All</span>
  {% elif p.student_type == 'NEW' %}<span class="badge badge-primary">New</span>
  {% else %}<span class="badge badge-secondary">Returning</span>{% endif %}
</td>
```

Also expose a per-item "missing sibling" warning in `_get_pricing_warnings`: when an item has
a CLASS or LEVEL row for one student type but no `ALL`/other-type row, warn admins that the
other type may resolve nothing for that item (or fall back to a different scope).

**Grouping:** sort the list by `scope → student_type → display_name` so the NEW/RETURNING
sibling rows sit adjacent and admins can diff their amounts at a glance.

### 4.5 Checkout Simplification

#### 4.5.1 `fees/checkout.py` — Simplified Options

The `get_checkout_options()` function currently assembles a complex cart with 
`outstanding`, `extras`, `next_term`, `bundle`, and `grouped_extras`. 

**Simplification:** Flatten extras into a single itemized list. Remove the bundle 
concept (it was redundant with checking all extras). The `outstanding` option stays 
as a single entry for the current invoice balance.

```python
@dataclass
class CheckoutOption:
    key: str              # 'outstanding' | f'item:{fee_price_pk}'
    kind: str             # 'outstanding' | 'item'
    label: str            # display name (FeePrice.display_name)
    amount: Decimal
    flexible: bool        # True only for outstanding
    fee_price_id: int | None
    term_id: int
    term_name: str
    invoice_id: int | None
    billed: bool = False
    settled: bool = False
```

The `bundle`, `next_term`, and `grouped_extras` fields are removed. 
Next-term items become regular items with a "Next Term" badge.

**Type-awareness:** all option assembly already flows through `resolve_student_type(student, term.session)`
and passes the resolved type to `_applicable_fee_structures(...)`. After the §4.2.2 fix the 
parent/student checkout automatically shows the NEW or RETURNING price rows for the student.
No extra work beyond what the resolver fix provides — but update the option `label` to use
`fs.display_name`.

#### 4.5.2 `fees/views.py` — `student_line_items_api`

Update the response format to include `display_name`:

```python
items.append({
    'id': item_id,
    'display_name': price.display_name,  # ← use this instead of category_name
    'category_name': cat.name,           # keep for backward compat
    'amount': str(amount),
    ...
})
```

### 4.6 Data Migration Strategy

#### Phase 1: Non-breaking additive changes (Safe deployment)
1. Add `FeePrice.name` field (blank=True, nullable=False, default='')
2. Add `InvoiceLineItem.item_name` field (blank=True, nullable=False, default='')
3. Run migrations

#### Phase 2: Populate new fields
```python
# management command: populate_fee_price_names
for fp in FeePrice.objects.filter(name='').select_related('category'):
    fp.name = fp.category.name
    fp.save(update_fields=['name'])
```

#### Phase 3: Update generation logic
Update `generate_invoice_for_student()` and `sync_class_invoices()` to populate `item_name`.

#### Phase 4: Update views and templates
Update all templates to use `display_name` / `item_name`.

#### Phase 5: Update tests
Update all affected tests.

---

## 5. Breaking Changes

| Change | Severity | Impact | Migration |
|--------|----------|--------|-----------|
| `FeePrice.name` field added | Non-breaking | Additive only (blank=True) | New migration |
| `InvoiceLineItem.item_name` added | Non-breaking | Additive only (blank=True) | New migration |
| Overpayment allowed in admin views | Behavioral | Admin can now overpay invoices | No migration |
| `Invoice.balance` may go negative | Behavioral | Existing code checking `balance <= 0` still works | No migration |
| Checkout option keys changed | **Breaking** | Frontend JS references to `extra:` keys change to `item:` | Template update |
| `student_line_items_api` response format | **Breaking** | `category_name` → `display_name` (keep both during transition) | View update |
| Price resolution now deterministic per student type | **Behavioral** | Type-specific row always beats `ALL` within a scope; previously nondeterministic. Invoice totals may change for students who have both a type-specific and an `ALL` price for the same item — this is the intended correctness fix, and re-sync (`sync_class_invoices`) catches affected invoices before fee collection. | No migration; run pricing tests + `sync_class_invoices` |
| `student_type='ALL'` param semantics clarified | **Behavioral** | `'ALL'` = aggregate report mode (no type filter); `'NEW'/'RETURNING'` = target mode with sub-scoping. Existing dashboard callers keep working but should switch to the student's resolved type when a specific student is involved. | Docstring + call-site audit |
| `visibility.py` name-set rules retired | **Behavioral** | RETURNING-specific applicability now lives on the item rows (no name-based hiding). Verify no portal regressions for the hidden-category names (`Registration Form`, `PTA`, `File Jacket`, `Maintenance`, `Examination Fee`) — they must either get explicit `NEW`-only rows or be left with no applicable row for RETURNING. | Template + view updates |
| FeeCategory name no longer primary display | Cosmetic | Admin sees FeePrice.name everywhere | Template update |

---

## 6. Test Impact Analysis

### 6.1 Tests Requiring Updates

| File | Count | Reason |
|------|-------|--------|
| `fees/tests.py` | ~15 of 113 | InvoiceLineItem creation now needs `item_name`; fee category tests unaffected |
| `fees/test_pricing.py` | ~5 of 30 | Return value now carries `.display_name` |
| `fees/tests_payment_management.py` | ~3 of 14 | Overpayment behavior changes |
| `fees/test_checkout.py` | ~4 of 14 | Checkout option key format changes |
| `fees/test_payment_recording.py` | ~2 of 13 | Overpayment edge cases |
| `school_admin/tests.py` | ~12 of 98 | Payment recording view tests, pricing form tests |

**Total affected: ~41 of ~468 tests (~9%)**

### 6.2 New Tests to Add

1. **`test_fee_price_display_name`** — FeePrice.name fallback to category.name
2. **`test_overpayment_records_full_amount`** — Admin overpayment creates Payment with full amount
3. **`test_overpayment_display_balance_clamped`** — Invoice.display_balance never negative
4. **`test_overpayment_selectors_annotated_balance_clamped`** — invoices_with_balance clamp
5. **`test_invoice_line_item_stores_item_name`** — item_name populated on generation
6. **`test_item_name_persists_after_category_rename`** — Denormalized name survives category changes
7. **`test_student_record_payment_overpayment`** — StudentRecordPaymentView accepts overpayment
8. **`test_checkout_option_key_format`** — New key format works
9. **`test_student_type_subscope_deterministic_new_beats_all`** — For a NEW student in JSS1A, when both `CLASS/JSS1A/NEW/Tuition @ 85000` and `CLASS/JSS1A/ALL/Tuition @ 80000` exist, resolve_prices picks 85000
10. **`test_student_type_subscope_returning_beats_all`** — Same scenario for RETURNING student
11. **`test_student_type_subscope_scope_wins_over_type`** — A `CLASS/ALL/Tuition @ 80000` row beats a `LEVEL/NEW/Tuition @ 85000` row for a NEW student in that class (scope is more specific than type)
12. **`test_returning_student_excluded_from_new_only_items`** — RETURNING student resolves no Registration Form / Uniforms rows; total is lower than NEW
13. **`test_new_student_no_returning_price_falls_back_to_all`** — NEW student has a CLASS/ALL/Tuition but no CLASS/NEW/Tuition row → ALL row is used (no row = no charge for that type)
14. **`test_override_precedes_price_resolution`** — FeePriceOverride(student, category) wins over both scope and type precedence
15. **`test_visibility_retired_no_hidden_by_name`** — AFTER retirement, items like "PTA" are excluded from RETURNING students by having no matching row, not by name filtering. Verify generation and display agree.
16. **`test_type_toggle_in_fees_tab_updates_total`** — Switching NEW→RETURNING in the admin fees-tab re-fires HTMX, list of items and Total Payable update

**New tests: ~16**

### 6.3 Tests Safe (No Changes)

- All `FeeCategory` CRUD tests
- All `Student` model tests
- All `Payment` status transition tests
- All `WebhookLog` tests
- All `FeeReceipt` tests
- All `InvoiceResetLog` tests
- All notification tests
- All role/permission tests
- All tenancy scoping tests

---

## 7. Execution Roadmap

### Phase 1: Model Layer (Day 1)
1. Add `FeePrice.name` field + migration
2. Add `InvoiceLineItem.item_name` field + migration
3. Add `FeePrice.display_name` property
4. Add `Invoice.display_balance` property
5. Write management command `populate_fee_price_names`
6. **Run:** `python manage.py test fees/tests.py fees/test_pricing.py`

### Phase 2: Pricing & Generation (Day 1-2)
1. Update `fees/pricing.py` — **deterministic two-stage sort** (scope, then student type) 
   per §4.2.2; add `type_precedence` key
2. Update `fees/pricing.py` — clarify `student_type` param docstring (`'ALL'` = aggregate mode, 
   `'NEW'/'RETURNING'` = target mode)
3. Retire `visibility.py` name-set imports per §4.2.3; move first-term (`CHRISTMAS_FEE`) 
   logic into the resolver path
4. Update `fees/generation.py` — populate `item_name` on generation
5. Update `fees/generation.py` — `sync_class_invoices()` populates `item_name`
6. Update `fees/selectors.py` — clamp annotated balance at 0
7. Run: `python manage.py test fees/`

### Phase 3: Admin Views — Overpayment (Day 2)
1. Update `school_admin/views/invoices.py` — `InvoiceDetailView.post()` remove balance cap
2. Update `school_admin/views/invoices.py` — verify `StudentRecordPaymentView` accepts overpayment
3. Add tests for overpayment scenarios
4. Run: `python manage.py test school_admin/tests.py`

### Phase 4: Admin UI — Pricing Forms (Day 2-3)
1. Update `fee_pricing_form.html` — add name field + student_type field + "apply to other type" checkbox
2. Update `fee_pricing_list.html` — show display_name + student-type column + missing-sibling warnings
3. Update `school_admin/views/fee_pricing.py` — save name field on create/edit, handle `apply_to_other_type`
4. Run: `python manage.py test school_admin/tests.py`

### Phase 5: Admin UI — Payment Recording (Day 3-4)
1. Update `student_line_items_api` response — add `display_name` + type-aware resolution 
   (forward `student_type` into resolver per §4.4.1)
2. Update `student_line_items_breakdown.html` — show item names, type-aware amounts
3. Redesign `_student_detail_fees_tab.html` — new layout with KPI cards + type toggle driving re-resolution
4. Add JavaScript for real-time amount_owing computation
5. Run: `python manage.py test school_admin/tests.py fees/tests.py`

### Phase 6: Admin UI — Invoice Detail (Day 4)
1. Update `invoice_detail.html` — remove max balance, add amount_owing display
2. Add JavaScript for overpayment UX
3. Run: `python manage.py test school_admin/tests.py`

### Phase 7: Checkout Simplification (Day 4-5)
1. Update `fees/checkout.py` — flatten checkout options
2. Update `fees/views.py` — update `student_line_items_api` response format
3. Update parent/student payment templates if affected
4. Run: `python manage.py test fees/`

### Phase 8: Test Cleanup & Final Pass (Day 5)
1. Update all affected tests for new behavior
2. Add new test cases for overpayment, display_name, item_name, and the 8 sub-scoping 
   cases (§6.2 items 9-16)
3. Remove obsolete tests (if any)
4. Full test suite: `python manage.py test`
5. Manual smoke test of admin payment flow (switch NEW↔RETURNING, verify totals + items change)

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Negative balance breaks downstream logic | Low | High | `Invoice.balance` already returns negative; `display_balance` is additive. Search for `balance < 0` and `balance <= 0` patterns to verify. |
| Paystack overpayment issues | Medium | High | Paystack payments use invoice balance as the cap. Need to verify `paystack_initiate()` handles negative balances. May need to clamp the Paystack amount to `display_balance`. |
| Existing data inconsistency | Low | Medium | `populate_fee_price_names` command backfills all FeePrice rows. Run before Phase 4 deployment. |
| HTMX partials break | Medium | Medium | The line items API is HTMX-compatible. Adding `display_name` to the response is additive. Test with both HTMX and JSON responses. |
| Checkout key format change breaks parent portal | Medium | Medium | Keep backward compat: support both `extra:PK` and `item:PK` keys during transition. |
| `visibility.py` retirement drops items from RETURNING students | Medium | High | Before shipping, audit which categories relied on the name-set hiding and add explicit `NEW`-only rows; token-invoice diff test (NEW vs RETURNING) per §6.2 item 15. |
| Student-type resolution change alters existing invoice totals | Medium | High | Run `sync_class_invoices` after deploy so affected invoices re-resolve before fee collection; pricing tests per §6.2 items 9-13 |

---

## 9. Compatibility Notes

- **Paystack integration:** `fees/paystack.py` uses `invoice.balance` to determine the 
  Paystack amount. When balance is negative (overpayment), Paystack should use `max(0, balance)` 
  as the charge amount. Verify `initiate_payment()` handles this.

- **Parent/Student portals:** `students/templates/make_payment.html` and 
  `students/templates/students/parent/child_detail.html` reference `category_name` 
  and `category.name`. Update to use `display_name` where available.

- **Receipt template:** `fees/receipt_view.html` shows `invoice.line_items` with 
  `category.name`. Update to show `item_name` or `display_name`.

- **Outstanding fees report:** `school_admin/views/invoices.py` — `OutstandingFeesReportView` 
  uses `balance_annotated`. Apply the `Greatest` clamp in the selector.

- **Dashboard:** `school_admin/views/dashboard.py` may reference `Invoice.balance`. 
  Verify it handles negative balances gracefully (it likely uses `balance > 0` filters which 
  already work).

- **Django admin:** `fees/admin.py` registers FeeCategory, FeePrice, Invoice, Payment. 
  Add `name` to FeePrice's `list_display`.

---

## 10. Migration Commands

```bash
# After deploying model changes:
python manage.py makemigrations fees --name add_feeprice_name_and_invoicelineitem_item_name
python manage.py migrate

# Backfill existing FeePrice names:
python manage.py shell -c "
from fees.models import FeePrice
for fp in FeePrice.objects.filter(name='').select_related('category'):
    fp.name = fp.category.name
    fp.save(update_fields=['name'])
print(f'Updated {FeePrice.objects.count()} FeePrice rows')
"

# Backfill existing InvoiceLineItem names:
python manage.py shell -c "
from fees.models import InvoiceLineItem
for li in InvoiceLineItem.objects.filter(item_name='').select_related('category'):
    li.item_name = li.category.name
    li.save(update_fields=['item_name'])
print(f'Updated {InvoiceLineItem.objects.count()} InvoiceLineItem rows')
"

# Run full test suite:
python manage.py test

# Verify no negative balance issues:
python manage.py shell -c "
from fees.models import Invoice
neg = Invoice.objects.filter(total_amount__lt=0)
print(f'{neg.count()} invoices with negative total')
"
```
