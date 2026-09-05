"""Fee and invoice management views for school admin portal."""
from decimal import Decimal
from uuid import uuid4

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from fees.models import FeeCategory, FeeStructure, FeePrice, Invoice, InvoiceLineItem, Payment, PaymentLineItem
from fees.pricing import resolve_price_for_student
from fees.selectors import invoices_with_balance
from students.models import Student, SchoolClass, ClassEnrollment


class FeeCategoryListView(RoleRequiredMixin, View):
    """List fee categories."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        categories = FeeCategory.objects.filter(school=school).order_by('name')
        return render(request, 'school_admin/fee_category_list.html', {
            'categories': categories,
        })


class FeeCategoryCreateView(RoleRequiredMixin, View):
    """Create a new fee category."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        return render(request, 'school_admin/fee_category_form.html', {
            'is_edit': False,
        })

    def post(self, request):
        school = request.school
        name = request.POST.get('name', '').strip()
        is_compulsory = request.POST.get('is_compulsory') == 'on'
        billing_cycle = request.POST.get('billing_cycle', 'PER_TERM')
        student_type = request.POST.get('student_type', 'ALL')

        if billing_cycle not in FeeCategory.BILLING_CYCLE_CHOICES:
            billing_cycle = 'PER_TERM'
        if student_type not in FeeCategory.STUDENT_TYPE_CHOICES:
            student_type = 'ALL'

        if not name:
            messages.error(request, 'Category name is required.')
            return render(request, 'school_admin/fee_category_form.html', {
                'is_edit': False,
            })

        if FeeCategory.objects.filter(school=school, name__iexact=name).exists():
            messages.error(request, 'A category with that name already exists.')
            return render(request, 'school_admin/fee_category_form.html', {
                'is_edit': False,
            })

        FeeCategory.objects.create(
            school=school, name=name, is_compulsory=is_compulsory,
            billing_cycle=billing_cycle, student_type=student_type,
        )
        messages.success(request, f'Category "{name}" created successfully.')
        return redirect('school_admin:fee_category_list')


class FeeCategoryEditView(RoleRequiredMixin, View):
    """Edit an existing fee category."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)
        return render(request, 'school_admin/fee_category_form.html', {
            'category': category,
            'is_edit': True,
        })

    def post(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)
        name = request.POST.get('name', '').strip()
        is_compulsory = request.POST.get('is_compulsory') == 'on'
        billing_cycle = request.POST.get('billing_cycle', category.billing_cycle)
        student_type = request.POST.get('student_type', category.student_type)

        if billing_cycle not in FeeCategory.BILLING_CYCLE_CHOICES:
            billing_cycle = category.billing_cycle
        if student_type not in FeeCategory.STUDENT_TYPE_CHOICES:
            student_type = category.student_type

        if not name:
            messages.error(request, 'Category name is required.')
            return render(request, 'school_admin/fee_category_form.html', {
                'category': category,
                'is_edit': True,
            })

        if FeeCategory.objects.filter(
            school=school, name__iexact=name,
        ).exclude(pk=category.pk).exists():
            messages.error(request, 'A category with that name already exists.')
            return render(request, 'school_admin/fee_category_form.html', {
                'category': category,
                'is_edit': True,
            })

        category.name = name
        category.is_compulsory = is_compulsory
        category.billing_cycle = billing_cycle
        category.student_type = student_type
        category.save()
        messages.success(request, f'Category "{name}" updated successfully.')
        return redirect('school_admin:fee_category_list')


class FeeCategoryDeleteView(RoleRequiredMixin, View):
    """Delete a fee category with confirmation."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)
        context = {
            'category': category,
            'structure_count': category.feestructure_set.count(),
            'line_item_count': InvoiceLineItem.objects.filter(category=category).count(),
        }
        return render(request, 'school_admin/fee_category_confirm_delete.html', context)

    def post(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)

        if category.feestructure_set.exists():
            messages.error(request, 'Cannot delete — assigned to fee structures.')
            return redirect('school_admin:fee_category_list')

        name = category.name
        category.delete()
        messages.success(request, f'Category "{name}" deleted successfully.')
        return redirect('school_admin:fee_category_list')


class FeePricingListView(RoleRequiredMixin, View):
    """List fee prices with scope, class, and term filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        scope = request.GET.get('scope', '')

        fee_prices = FeePrice.objects.filter(school=school).select_related('school_class', 'term', 'category')

        if scope:
            fee_prices = fee_prices.filter(scope=scope)

        class_id = request.GET.get('class_id', '')
        if class_id:
            fee_prices = fee_prices.filter(school_class_id=class_id)

        term_id = request.GET.get('term_id', '')
        if term_id:
            fee_prices = fee_prices.filter(term_id=term_id)

        pricing = list(fee_prices)
        pricing.sort(key=lambda p: (p.scope, str(p.school_class or ''), str(p.term or ''), p.category.name))

        classes = SchoolClass.objects.filter(school=school, is_active=True)
        terms = Term.for_current_session(school)

        warnings = self._get_pricing_warnings(school)

        return render(request, 'school_admin/fee_pricing_list.html', {
            'pricing': pricing,
            'classes': classes,
            'terms': terms,
            'filter_class': class_id,
            'filter_term': term_id,
            'filter_scope': scope,
            'warnings': warnings,
        })

    def _get_pricing_warnings(self, school):
        warnings = []
        current_term = Term.objects.filter(school=school, is_current=True).first()
        if not current_term:
            return warnings

        compulsory_categories = FeeCategory.objects.filter(school=school, is_compulsory=True)
        for category in compulsory_categories:
            if category.billing_cycle == 'ONE_TIME':
                has_price = FeePrice.objects.filter(
                    school=school,
                    category=category,
                    term__isnull=True,
                    is_active=True,
                ).exists()
            else:
                has_price = FeePrice.objects.filter(
                    school=school,
                    category=category,
                    term=current_term,
                    is_active=True,
                ).exists()
            if not has_price:
                if category.billing_cycle == 'ONE_TIME':
                    warnings.append({
                        'message': f'Compulsory one-time category "{category.name}" has no price set.',
                        'category_id': category.id,
                        'term_id': None,
                    })
                else:
                    warnings.append({
                        'message': f'Compulsory category "{category.name}" has no price for {current_term.name}.',
                        'category_id': category.id,
                        'term_id': current_term.id,
                    })

        return warnings


class FeePricingBulkCopyView(RoleRequiredMixin, View):
    """Copy fee prices from a previous term to the current term."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        terms = Term.for_current_session(school)
        return render(request, 'school_admin/fee_pricing_bulk_copy.html', {
            'terms': terms,
        })

    def post(self, request):
        school = request.school
        from_term_id = request.POST.get('from_term_id', '')
        to_term_id = request.POST.get('to_term_id', '')

        if not from_term_id or not to_term_id:
            messages.error(request, 'Please select both source and target terms.')
            return redirect('school_admin:fee_pricing_bulk_copy')

        from_term = get_object_or_404(Term, school=school, pk=from_term_id)
        to_term = get_object_or_404(Term, school=school, pk=to_term_id)

        if from_term_id == to_term_id:
            messages.error(request, 'Source and target terms must be different.')
            return redirect('school_admin:fee_pricing_bulk_copy')

        created = 0
        skipped = 0

        source_prices = FeePrice.objects.filter(school=school, term=from_term)
        for price in source_prices:
            exists = FeePrice.objects.filter(
                school=school,
                scope=price.scope,
                school_class=price.school_class,
                level=price.level,
                term=to_term,
                category=price.category,
                student_type=price.student_type,
            ).exists()
            if exists:
                skipped += 1
                continue

            FeePrice.objects.create(
                school=school,
                scope=price.scope,
                school_class=price.school_class,
                level=price.level,
                term=to_term,
                category=price.category,
                amount=price.amount,
                student_type=price.student_type,
                is_active=True,
                effective_from=None,
                effective_to=None,
            )
            created += 1

        messages.success(
            request,
            f'Copied {created} fee price(s) from {from_term.name} to {to_term.name}. {skipped} skipped because they already exist.',
        )
        return redirect('school_admin:fee_pricing_list')


class FeePricingPromoteView(RoleRequiredMixin, View):
    """Promote school-wide prices to level or class prices."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request):
        school = request.school
        price_id = request.POST.get('price_id')
        target_scope = request.POST.get('target_scope')
        target_class_id = request.POST.get('target_class_id')
        target_level = request.POST.get('target_level')

        price = get_object_or_404(FeePrice, school=school, pk=price_id)

        if price.scope != FeePrice.SCOPE_SCHOOL_WIDE:
            messages.error(request, 'Only school-wide prices can be promoted.')
            return redirect('school_admin:fee_pricing_list')

        if target_scope == FeePrice.SCOPE_CLASS and not target_class_id:
            messages.error(request, 'Target class is required for class scope.')
            return redirect('school_admin:fee_pricing_list')

        if target_scope == FeePrice.SCOPE_LEVEL and not target_level:
            messages.error(request, 'Target level is required for level scope.')
            return redirect('school_admin:fee_pricing_list')

        exists = FeePrice.objects.filter(
            school=school,
            scope=target_scope,
            school_class_id=target_class_id or None,
            level=target_level or '',
            term=price.term,
            category=price.category,
            student_type=price.student_type,
        ).exists()

        if exists:
            messages.error(request, 'A price already exists at the target scope.')
            return redirect('school_admin:fee_pricing_list')

        FeePrice.objects.create(
            school=school,
            scope=target_scope,
            school_class_id=target_class_id or None,
            level=target_level or '',
            term=price.term,
            category=price.category,
            amount=price.amount,
            student_type=price.student_type,
            is_active=True,
            effective_from=None,
            effective_to=None,
        )

        messages.success(
            request,
            f'Promoted {price.category.name} from school-wide to {dict(FeePrice.SCOPE_CHOICES)[target_scope]}.',
        )
        return redirect('school_admin:fee_pricing_list')


class FeePricingCreateView(RoleRequiredMixin, View):
    """Add a fee price with scope selection (school-wide, level, or class-specific)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        preselect_category_id = request.GET.get('category_id')
        preselect_term_id = request.GET.get('term_id')
        return render(request, 'school_admin/fee_pricing_form.html', {
            'is_edit': False,
            'categories': FeeCategory.objects.filter(school=school),
            'classes': SchoolClass.objects.filter(school=school, is_active=True),
            'terms': Term.for_current_session(school),
            'scopes': FeePrice.SCOPE_CHOICES,
            'selected_category_id': int(preselect_category_id) if preselect_category_id and preselect_category_id.isdigit() else None,
            'selected_term_id': int(preselect_term_id) if preselect_term_id and preselect_term_id.isdigit() else None,
            'selected_scope': 'SCHOOL_WIDE',
        })

    def post(self, request):
        school = request.school
        category_id = request.POST.get('category_id', '')
        scope = request.POST.get('scope', FeePrice.SCOPE_CLASS)
        class_id = request.POST.get('class_id', '')
        level = request.POST.get('level', '')
        term_id = request.POST.get('term_id', '')
        raw_amount = request.POST.get('amount', '').strip()
        student_type = request.POST.get('student_type', 'ALL')
        effective_from = request.POST.get('effective_from', '')
        effective_to = request.POST.get('effective_to', '')

        if student_type not in FeeCategory.STUDENT_TYPE_CHOICES:
            student_type = 'ALL'

        categories = FeeCategory.objects.filter(school=school)
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        terms = Term.for_current_session(school)

        def re_render():
            return render(request, 'school_admin/fee_pricing_form.html', {
                'is_edit': False,
                'categories': categories,
                'classes': classes,
                'terms': terms,
                'scopes': FeePrice.SCOPE_CHOICES,
                'selected_category_id': category_id,
                'selected_scope': scope,
                'selected_class_id': class_id,
                'selected_level': level,
                'selected_term_id': term_id,
                'selected_student_type': student_type,
                'selected_effective_from': effective_from,
                'selected_effective_to': effective_to,
                'entered_amount': raw_amount,
            })

        if not category_id or not raw_amount:
            messages.error(request, 'Category and amount are required.')
            return re_render()

        category = get_object_or_404(FeeCategory, school=school, pk=category_id)
        school_class = None
        if class_id and scope == FeePrice.SCOPE_CLASS:
            school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
        elif class_id and scope != FeePrice.SCOPE_CLASS:
            messages.error(request, 'Class must not be selected for school-wide or level-scoped prices.')
            return re_render()

        term = None
        if term_id:
            term = get_object_or_404(Term, school=school, pk=term_id)

        try:
            amount = Decimal(raw_amount)
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return re_render()

        if amount < 0:
            messages.error(request, 'Amount cannot be negative.')
            return re_render()

        if FeePrice.objects.filter(
            school=school,
            scope=scope,
            school_class=school_class,
            level=level,
            term=term,
            category=category,
            student_type=student_type,
        ).exists():
            messages.error(request, 'A fee price already exists for this scope, class/level, term, category and student type.')
            return re_render()

        fp = FeePrice.objects.create(
            school=school,
            scope=scope,
            school_class=school_class,
            level=level,
            term=term,
            category=category,
            amount=amount,
            student_type=student_type,
            effective_from=effective_from if effective_from else None,
            effective_to=effective_to if effective_to else None,
        )

        if term and school_class:
            from fees.generation import generate_invoices_for_class
            generated = generate_invoices_for_class(school_class, term)
            messages.success(
                request,
                f'Price added: {category.name} — {school_class.name} ({term.name}, {student_type}). '
                f'{generated} invoice(s) generated for students without one.',
            )
        else:
            messages.success(
                request,
                f'Price added: {category.name} ({scope}, {student_type}).',
            )
        return redirect('school_admin:fee_pricing_list')


class FeePricingEditView(RoleRequiredMixin, View):
    """Edit a fee price (FeePrice or deprecated FeeStructure)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        price = get_object_or_404(FeePrice, school=school, pk=pk)
        return render(request, 'school_admin/fee_pricing_form.html', {
            'is_edit': True,
            'price': price,
            'categories': FeeCategory.objects.filter(school=school),
            'classes': SchoolClass.objects.filter(school=school, is_active=True),
            'terms': Term.objects.filter(school=school).order_by('-start_date'),
            'scopes': FeePrice.SCOPE_CHOICES,
            'selected_category_id': price.category_id,
            'selected_scope': price.scope,
            'selected_class_id': price.school_class_id,
            'selected_level': price.level,
            'selected_term_id': price.term_id,
            'selected_student_type': price.student_type,
            'selected_effective_from': price.effective_from,
            'selected_effective_to': price.effective_to,
        })

    def post(self, request, pk):
        school = request.school
        price = get_object_or_404(FeePrice, school=school, pk=pk)

        category_id = request.POST.get('category_id', '')
        scope = request.POST.get('scope', price.scope)
        class_id = request.POST.get('class_id', '')
        level = request.POST.get('level', '')
        term_id = request.POST.get('term_id', '')
        raw_amount = request.POST.get('amount', '').strip()
        student_type = request.POST.get('student_type', price.student_type)
        effective_from = request.POST.get('effective_from', '')
        effective_to = request.POST.get('effective_to', '')

        if student_type not in FeeCategory.STUDENT_TYPE_CHOICES:
            student_type = price.student_type

        categories = FeeCategory.objects.filter(school=school)
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        terms = Term.for_current_session(school)

        def re_render():
            return render(request, 'school_admin/fee_pricing_form.html', {
                'is_edit': True,
                'price': price,
                'categories': categories,
                'classes': classes,
                'terms': terms,
                'scopes': FeePrice.SCOPE_CHOICES,
                'selected_category_id': category_id,
                'selected_scope': scope,
                'selected_class_id': class_id,
                'selected_level': level,
                'selected_term_id': term_id,
                'selected_student_type': student_type,
                'selected_effective_from': effective_from,
                'selected_effective_to': effective_to,
                'entered_amount': raw_amount,
            })

        if not category_id or not raw_amount:
            messages.error(request, 'Category and amount are required.')
            return re_render()

        category = get_object_or_404(FeeCategory, school=school, pk=category_id)
        school_class = None
        if class_id and scope == FeePrice.SCOPE_CLASS:
            school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
        elif class_id and scope != FeePrice.SCOPE_CLASS:
            messages.error(request, 'Class must not be selected for school-wide or level-scoped prices.')
            return re_render()

        term = None
        if term_id:
            term = get_object_or_404(Term, school=school, pk=term_id)

        try:
            amount = Decimal(raw_amount)
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return re_render()

        if amount < 0:
            messages.error(request, 'Amount cannot be negative.')
            return re_render()

        if FeePrice.objects.filter(
            school=school,
            scope=scope,
            school_class=school_class,
            level=level,
            term=term,
            category=category,
            student_type=student_type,
        ).exclude(pk=pk).exists():
            messages.error(request, 'A fee price already exists for this scope, class/level, term, category and student type.')
            return re_render()

        price.scope = scope
        price.school_class = school_class
        price.level = level
        price.term = term
        price.category = category
        price.amount = amount
        price.student_type = student_type
        price.effective_from = effective_from if effective_from else None
        price.effective_to = effective_to if effective_to else None
        price.save()

        if term and school_class:
            from fees.generation import generate_invoices_for_class, sync_class_invoices
            generated = generate_invoices_for_class(school_class, term)
            re_priced = sync_class_invoices(school_class, term)
            messages.success(
                request,
                f'Price updated: {category.name} — {school_class.name} ({term.name}, {student_type}). '
                f'{generated} invoice(s) generated, {re_priced} unpaid invoice(s) re-priced.',
            )
        else:
            messages.success(
                request,
                f'Price updated: {category.name} ({scope}, {student_type}).',
            )
        return redirect('school_admin:fee_pricing_list')


class FeePricingDeleteView(RoleRequiredMixin, View):
    """Delete a fee price with confirmation."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        price = get_object_or_404(FeePrice, school=school, pk=pk)
        return render(request, 'school_admin/fee_pricing_confirm_delete.html', {
            'price': price,
        })

    def post(self, request, pk):
        school = request.school
        price = get_object_or_404(FeePrice, school=school, pk=pk)
        message = (
            f'Price removed: {price.category.name} — '
            f'{price.get_scope_display()} ({price.term.name if price.term else "One-time"}).'
        )
        price.delete()
        messages.success(request, message)
        return redirect('school_admin:fee_pricing_list')


class InvoiceListView(RoleRequiredMixin, View):
    """List invoices with filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        invoices = Invoice.objects.filter(
            school=school
        ).select_related('student', 'student__user', 'term')

        term_id = request.GET.get('term_id', '')
        if term_id:
            invoices = invoices.filter(term_id=term_id)

        from fees.selectors import invoices_with_balance
        invoices = invoices_with_balance(invoices)

        status = request.GET.get('status', '')
        if status == 'PAID':
            invoices = invoices.filter(balance_annotated__lte=0)
        elif status == 'PARTIAL':
            invoices = invoices.filter(balance_annotated__gt=0, amount_paid_annotated__gt=0)
        elif status == 'UNPAID':
            invoices = invoices.filter(amount_paid_annotated__lte=0)

        student_q = request.GET.get('q', '')
        if student_q:
            invoices = invoices.filter(
                student__user__first_name__icontains=student_q
            ) | invoices.filter(
                student__user__last_name__icontains=student_q
            )

        from core.models import Term
        terms = Term.for_current_session(school)

        return render(request, 'school_admin/invoice_list.html', {
            'invoices': invoices,
            'terms': terms,
            'filter_term': term_id,
            'filter_status': status,
            'q': student_q,
        })


class InvoiceDetailView(RoleRequiredMixin, View):
    """Invoice detail with payment history."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        invoice = get_object_or_404(Invoice, school=school, pk=pk)
        line_items = invoice.line_items.all()
        payments = invoice.payments.select_related('recorded_by').order_by('-paid_on')

        return render(request, 'school_admin/invoice_detail.html', {
            'invoice': invoice,
            'line_items': line_items,
            'payments': payments,
        })

    def post(self, request, pk):
        """Record a cash payment against this invoice."""
        school = request.school
        invoice = get_object_or_404(Invoice, school=school, pk=pk)

        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return redirect('school_admin:invoice_detail', pk=pk)

        if amount <= 0:
            messages.error(request, 'Amount must be positive.')
            return redirect('school_admin:invoice_detail', pk=pk)
        if amount > invoice.balance:
            messages.error(
                request,
                f'Amount must be at most the outstanding balance '
                f'(₦{invoice.balance:,.2f}).',
            )
            return redirect('school_admin:invoice_detail', pk=pk)

        reference = request.POST.get('reference', '').strip()
        method = request.POST.get('method', '')
        if method not in Payment.Method.values:
            method = Payment.Method.CASH
        # Blank references collide with unique_together (school, reference):
        # auto-generate one so repeated cash/POS entries never hit IntegrityError.
        # Paystack references are never auto-generated — they must be real,
        # and full_clean() rejects a Paystack payment without one.
        if not reference and method != Payment.Method.PAYSTACK:
            reference = f'ADM-{invoice.pk}-{uuid4().hex[:8].upper()}'
        payment = Payment(
            school=school,
            invoice=invoice,
            amount=amount,
            method=method,
            reference=reference,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=request.user,
            paid_by_name=request.POST.get('paid_by_name', '').strip(),
            paid_by_relation=request.POST.get('paid_by_relation', '').strip(),
        )
        try:
            payment.full_clean()
            payment.save()
        except ValidationError as exc:
            messages.error(request, f'Payment rejected: {"; ".join(" ".join(v) for v in exc.message_dict.values())}')
            return redirect('school_admin:invoice_detail', pk=pk)
        messages.success(request, f'Payment of NGN{amount} recorded.')
        return redirect('school_admin:invoice_detail', pk=pk)


class GenerateInvoicesView(RoleRequiredMixin, View):
    """Generate invoices for all active students in a term."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        from core.models import Term
        school = request.school
        terms = Term.for_current_session(school)
        return render(request, 'school_admin/generate_invoices.html', {
            'terms': terms,
        })

    def post(self, request):
        from core.models import Term
        school = request.school
        term_id = request.POST.get('term_id')

        if not term_id:
            messages.error(request, 'Please select a term.')
            return redirect('school_admin:generate_invoices')

        term = get_object_or_404(Term, school=school, pk=term_id)

        from fees.generation import generate_invoices_for_term

        generated, skipped = generate_invoices_for_term(school, term)

        messages.success(
            request,
            f'Generated {generated} invoice(s). {skipped} skipped (already exist or no enrollment).'
        )
        return redirect('school_admin:invoice_list')


class OutstandingFeesReportView(RoleRequiredMixin, View):
    """Dedicated outstanding-fees report: KPIs, breakdowns, debtor list, CSV export."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school

        # ── Term scope: default to current term, 'all' for everything ──
        term_id = request.GET.get('term_id', '')
        current_term = Term.objects.filter(school=school, is_current=True).first()
        if term_id == 'all':
            selected_term = None
        elif term_id:
            selected_term = get_object_or_404(Term, school=school, pk=term_id)
        else:
            selected_term = current_term

        class_id = request.GET.get('class_id', '')
        status_filter = request.GET.get('status', '')
        q = request.GET.get('q', '').strip()

        terms = Term.for_current_session(school)
        classes = SchoolClass.objects.filter(
            school=school, is_active=True
        ).order_by('level', 'name')

        # ── Base debtor queryset: annotated, filtered, current class name ──
        current_class_name = ClassEnrollment.objects.filter(
            student=OuterRef('student_id'),
            is_current=True,
        ).values('school_class__name')[:1]

        qs = invoices_with_balance(Invoice.objects.filter(school=school))
        if selected_term:
            qs = qs.filter(term=selected_term)
        if class_id:
            qs = qs.filter(
                student__enrollments__school_class_id=class_id,
                student__enrollments__is_current=True,
            )
        if status_filter == 'UNPAID':
            qs = qs.filter(amount_paid_annotated=Decimal('0.00'))
        elif status_filter == 'PARTIAL':
            qs = qs.filter(amount_paid_annotated__gt=Decimal('0.00'))
        if q:
            qs = qs.filter(
                Q(student__user__first_name__icontains=q)
                | Q(student__user__last_name__icontains=q)
                | Q(student__admission_number__icontains=q)
            )
        qs = qs.filter(balance_annotated__gt=Decimal('0.00'))
        qs = qs.select_related('student__user', 'term').annotate(
            current_class_name=Subquery(current_class_name)
        )

        # ── CSV export reuses the exact same filtered queryset ──
        if request.GET.get('export') == 'csv':
            return self._csv_response(qs)

        # ── KPIs ──
        total_outstanding = qs.aggregate(
            total=Sum('balance_annotated')
        )['total'] or Decimal('0.00')
        students_owing = qs.values('student').distinct().count()
        unpaid_count = qs.filter(amount_paid_annotated=Decimal('0.00')).count()
        partial_count = qs.filter(amount_paid_annotated__gt=Decimal('0.00')).count()

        outstanding_invoices = invoices_with_balance(
            Invoice.objects.filter(school=school)
        ).filter(balance_annotated__gt=Decimal('0.00'))
        if selected_term:
            outstanding_invoices = outstanding_invoices.filter(term=selected_term)
        payments_qs = Payment.objects.filter(
            school=school,
            status=Payment.Status.CONFIRMED,
            invoice__in=outstanding_invoices,
        )
        total_collected = payments_qs.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        # ── Breakdowns ──
        by_class = qs.values('student__enrollments__school_class__name').annotate(
            total=Sum('balance_annotated'),
            students=Count('student', distinct=True),
        ).order_by('-total')

        by_term = []
        if not selected_term:
            by_term = qs.values('term__name').annotate(
                total=Sum('balance_annotated'),
                invoices=Count('id'),
            ).order_by('-total')

        # ── Debtor rows (age buckets computed in Python — small result set) ──
        debtors = [self._debtor_row(inv) for inv in qs.order_by('-balance_annotated')]

        return render(request, 'school_admin/outstanding_fees.html', {
            'terms': terms,
            'classes': classes,
            'filter_term': term_id,
            'filter_class': class_id,
            'filter_status': status_filter,
            'q': q,
            'selected_term': selected_term,
            'total_outstanding': total_outstanding,
            'students_owing': students_owing,
            'unpaid_count': unpaid_count,
            'partial_count': partial_count,
            'total_collected': total_collected,
            'by_class': by_class,
            'by_term': by_term,
            'debtors': debtors,
        })

    def _debtor_row(self, invoice):
        """Build a display row for one outstanding invoice."""
        paid = invoice.amount_paid_annotated
        balance = invoice.balance_annotated
        status = 'PARTIAL' if paid > Decimal('0.00') else 'UNPAID'

        age_days = (timezone.localdate() - invoice.generated_on.date()).days
        if age_days > 60:
            age_bucket = '60+'
        elif age_days > 30:
            age_bucket = '31-60'
        else:
            age_bucket = '0-30'

        return {
            'invoice': invoice,
            'student': invoice.student.user.get_full_name() or invoice.student.user.username,
            'admission_number': invoice.student.admission_number,
            'class_name': invoice.current_class_name or '—',
            'term': invoice.term.name,
            'total': invoice.total_amount,
            'paid': paid,
            'balance': balance,
            'status': status,
            'age_days': age_days,
            'age_bucket': age_bucket,
        }

    def _csv_response(self, qs):
        """Serve the filtered debtor list as a CSV download."""
        from core.utils import csv_response

        response, writer = csv_response(
            'outstanding_fees.csv',
            header=[
                'Student', 'Admission No', 'Class', 'Term',
                'Total (NGN)', 'Paid (NGN)', 'Balance (NGN)', 'Status', 'Age Bucket',
            ],
        )
        for inv in qs.order_by('-balance_annotated'):
            row = self._debtor_row(inv)
            writer.writerow([
                row['student'],
                row['admission_number'],
                row['class_name'],
                row['term'],
                str(row['total']),
                str(row['paid']),
                str(row['balance']),
                row['status'],
                row['age_bucket'],
            ])
        return response


class PendingTransfersView(RoleRequiredMixin, View):
    """List bank-transfer payments awaiting admin confirmation."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        payments = Payment.objects.filter(
            school=school,
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        ).select_related(
            'student__user', 'invoice__student__user', 'invoice__term',
        ).prefetch_related('invoice__line_items__category').order_by('-paid_on')

        total_pending = payments.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        return render(request, 'school_admin/pending_transfers.html', {
            'payments': payments,
            'total_pending': total_pending,
        })


class PendingTransferConfirmView(RoleRequiredMixin, View):
    """Confirm a pending bank-transfer payment and issue its receipt."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)

        if payment.status != Payment.Status.PENDING:
            messages.info(request, 'This payment has already been processed.')
            return redirect('school_admin:pending_transfers')

        with transaction.atomic():
            payment.status = Payment.Status.CONFIRMED
            payment.paid_on = timezone.now()
            payment.recorded_by = request.user
            payment.confirmed_by = request.user
            payment.confirmed_at = timezone.now()
            payment.webhook_processed = True
            payment.save(update_fields=[
                'status', 'paid_on', 'recorded_by', 'confirmed_by',
                'confirmed_at', 'webhook_processed',
            ])
            from fees.paystack import issue_receipt
            issue_receipt(payment)
            from notifications.utils import notify_many
            from accounts.models import Roles, User

            recipients = []
            if payment.student_id:
                student_user = User.objects.filter(pk=payment.student.user_id).first()
                if student_user:
                    recipients.append(student_user)
                recipients += [
                    link.guardian
                    for link in payment.student.guardian_links.select_related('guardian').all()
                    if link.guardian_id
                ]
            notify_many(
                recipients=recipients,
                channel='IN_APP',
                subject=f'Bank transfer confirmed: ₦{payment.amount:,.2f}',
                message=(
                    f'Your bank transfer of ₦{payment.amount:,.2f} has been confirmed.'
                ),
                reference=f'transfer-confirm:{payment.id}',
                url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
            )

        messages.success(request, f'Payment of ₦{payment.amount:,.2f} confirmed.')
        return redirect('school_admin:pending_transfers')


class PendingTransferRejectView(RoleRequiredMixin, View):
    """Mark a pending bank-transfer payment as failed."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)

        if payment.status != Payment.Status.PENDING:
            messages.info(request, 'This payment has already been processed.')
            return redirect('school_admin:pending_transfers')

        payment.status = Payment.Status.FAILED
        payment.save(update_fields=['status'])
        from notifications.utils import notify_many
        from accounts.models import User

        recipients = []
        if payment.student_id:
            student_user = User.objects.filter(pk=payment.student.user_id).first()
            if student_user:
                recipients.append(student_user)
            recipients += [
                link.guardian
                for link in payment.student.guardian_links.select_related('guardian').all()
                if link.guardian_id
            ]
        notify_many(
            recipients=recipients,
            channel='IN_APP',
            subject=f'Bank transfer rejected: ₦{payment.amount:,.2f}',
            message=(
                f'Your bank transfer of ₦{payment.amount:,.2f} was rejected. '
                f'Please contact the school.'
            ),
            reference=f'transfer-reject:{payment.id}',
            url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
        )

        messages.info(request, 'Payment marked failed.')
        return redirect('school_admin:pending_transfers')


class PaymentEditView(RoleRequiredMixin, View):
    """Edit a recorded payment (amount, method, payer, reference)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)
        return render(request, 'school_admin/payment_edit.html', {
            'payment': payment,
        })

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)
        back = redirect('school_admin:invoice_detail', pk=payment.invoice_id) \
            if payment.invoice_id else redirect('school_admin:student_detail', pk=payment.student_id)

        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return back
        if amount <= 0:
            messages.error(request, 'Amount must be positive.')
            return back

        method = request.POST.get('method', '')
        if method not in Payment.Method.values:
            messages.error(request, 'Invalid payment method.')
            return back

        payment.amount = amount
        payment.method = method
        payment.paid_by_name = request.POST.get('paid_by_name', '').strip()
        payment.paid_by_relation = request.POST.get('paid_by_relation', '').strip()
        payment.reference = request.POST.get('reference', '').strip() or None
        payment.save(update_fields=[
            'amount', 'method', 'paid_by_name', 'paid_by_relation', 'reference',
        ])
        messages.success(request, 'Payment updated.')
        return back


class PaymentDeleteView(RoleRequiredMixin, View):
    """Delete a wrongly recorded payment."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)
        back = redirect('school_admin:invoice_detail', pk=payment.invoice_id) \
            if payment.invoice_id else redirect('school_admin:student_detail', pk=payment.student_id)

        amount = payment.amount
        payment.delete()
        messages.success(request, f'Payment of ₦{amount:,.2f} deleted.')
        return back


class StudentRecordPaymentView(RoleRequiredMixin, View):
    """Record a payment against a student, optionally linked to an invoice.

    Supports three selection modes:
    1. Invoice — selected line items belong to a specific invoice
    2. Class Total — selected items are from FeePrice resolution (no invoice yet)
    3. None — free-form payment against the student only

    Selected items are tracked as PaymentLineItem rows so receipts
    and statements can show exactly what was paid for.
    """

    allowed_roles = [Roles.ADMIN]

    @staticmethod
    def _auto_flip_student_type(student, payment_items, payment):
        """If the payment covers the Registration Form fee, mark the student
        as RETURNING for subsequent terms and stamp registration_paid_term.
        """
        if student.student_type == 'RETURNING':
            return
        if student.registration_paid_term_id:
            return
        registration_paid = any(
            (it.get('category') and it['category'].name == 'Registration Form')
            for it in payment_items
        )
        if not registration_paid:
            return
        from core.models import Term
        term = None
        if payment.invoice_id and payment.invoice.term_id:
            term = payment.invoice.term
        else:
            term = Term.objects.filter(
                school=student.school, is_current=True
            ).first()
        student.registration_paid_term = term
        student.student_type = 'RETURNING'
        student.save(update_fields=['registration_paid_term', 'student_type'])

    def post(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)

        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return redirect('school_admin:student_detail', pk=student.pk)
        if amount <= 0:
            messages.error(request, 'Amount must be positive.')
            return redirect('school_admin:student_detail', pk=student.pk)

        method = request.POST.get('method', '')
        if method not in Payment.Method.values:
            messages.error(request, 'Invalid payment method.')
            return redirect('school_admin:student_detail', pk=student.pk)

        scope = request.POST.get('scope_select', '')
        selected_line_item_ids = request.POST.getlist('selected_line_items')
        custom_labels = request.POST.getlist('custom_labels')
        custom_amounts = request.POST.getlist('custom_amounts')
        custom_enabled = request.POST.getlist('custom_enabled')

        invoice = None
        payment_items = []
        custom_lines_summary = []
        merged_description = request.POST.get('description', '').strip()

        if selected_line_item_ids:
            from collections import defaultdict
            items_by_invoice = defaultdict(list)

            for raw_id in selected_line_item_ids:
                if not raw_id or ':' not in raw_id:
                    continue
                source, _, id_str = raw_id.partition(':')
                try:
                    pk_value = int(id_str)
                except (ValueError, TypeError):
                    continue

                if source == 'invoice':
                    li = InvoiceLineItem.objects.filter(
                        pk=pk_value, invoice__student=student
                    ).select_related('category', 'invoice__term').first()
                    if not li:
                        continue
                    items_by_invoice[li.invoice_id].append(li)
                    payment_items.append({
                        'kind': 'invoice_line',
                        'label': li.category.name,
                        'amount': li.amount,
                        'category': li.category,
                        'term': li.invoice.term,
                        'session': li.invoice.term.session if li.invoice.term else None,
                        'invoice': li.invoice,
                        'source_key': f'manual:invoice:{li.pk}',
                    })
                elif source == 'price':
                    fp = FeePrice.objects.filter(pk=pk_value).select_related('category', 'term').first()
                    if not fp:
                        continue
                    try:
                        resolved_amount = resolve_price_for_student(
                            school=school,
                            student=student,
                            school_class=fp.school_class,
                            category=fp.category,
                            term=fp.term,
                        ) or fp.amount
                    except Exception:
                        resolved_amount = fp.amount
                    payment_items.append({
                        'kind': 'fee_price',
                        'label': fp.category.name,
                        'amount': resolved_amount,
                        'category': fp.category,
                        'term': fp.term,
                        'session': fp.term.session if fp.term else None,
                        'invoice': None,
                        'source_key': f'manual:price:{fp.pk}',
                    })

            if items_by_invoice:
                invoice = Invoice.objects.filter(
                    pk=list(items_by_invoice.keys())[0],
                    school=school,
                ).first()
            elif not payment_items:
                messages.error(request, 'No valid line items selected.')
                return redirect('school_admin:student_detail', pk=student.pk)

        # Custom "something else" rows — add as KIND_EXTRA line items with no invoice link.
        custom_lines_summary = []
        for i, label in enumerate(custom_labels):
            if not custom_enabled or i >= len(custom_enabled):
                continue
            label_clean = (label or '').strip()
            try:
                amt_clean = Decimal(custom_amounts[i]) if i < len(custom_amounts) else Decimal('0')
            except (ValueError, ArithmeticError, IndexError):
                amt_clean = Decimal('0')
            if amt_clean <= 0 or not label_clean:
                continue
            custom_lines_summary.append(f'{label_clean}: \u20a6{amt_clean:,.2f}')
            payment_items.append({
                'kind': 'custom',
                'label': label_clean,
                'amount': amt_clean,
                'category': None,
                'term': None,
                'session': None,
                'invoice': None,
                'source_key': f'manual:custom:{student.pk}:{i}',
            })
        if custom_lines_summary:
            existing_desc = request.POST.get('description', '').strip()
            merged_description = (
                existing_desc + ' | ' + '; '.join(custom_lines_summary)
                if existing_desc else '; '.join(custom_lines_summary)
            )
        else:
            invoice_id = request.POST.get('invoice_id', '')
            if invoice_id:
                invoice = get_object_or_404(Invoice, school=school, pk=invoice_id)
                if invoice.student_id != student.pk:
                    messages.error(request, 'That invoice belongs to a different student.')
                    return redirect('school_admin:student_detail', pk=student.pk)

        with transaction.atomic():
            payment = Payment.objects.create(
                school=school,
                invoice=invoice,
                student=student,
                amount=amount,
                method=method,
                reference=request.POST.get('reference', '').strip() or None,
                status=Payment.Status.CONFIRMED,
                paid_on=timezone.now(),
                recorded_by=request.user,
                description=merged_description,
                paid_by_name=request.POST.get('paid_by_name', '').strip(),
                paid_by_relation=request.POST.get('paid_by_relation', '').strip(),
            )

            for item in payment_items:
                PaymentLineItem.objects.create(
                    school=school,
                    payment=payment,
                    kind=PaymentLineItem.KIND_EXTRA,
                    label=item['label'],
                    amount=item['amount'],
                    source_key=item['source_key'],
                    category=item['category'],
                    term=item['term'],
                    session=item['session'],
                    invoice=item['invoice'],
                )

            self._auto_flip_student_type(student, payment_items, payment)

        from fees.paystack import issue_receipt
        issue_receipt(payment)
        from notifications.utils import notify_many
        from accounts.models import User

        recipients = []
        student_user = User.objects.filter(pk=student.user_id).first()
        if student_user:
            recipients.append(student_user)
        recipients += [
            link.guardian
            for link in student.guardian_links.select_related('guardian').all()
            if link.guardian_id
        ]
        notify_many(
            recipients=recipients,
            channel='IN_APP',
            subject=f'Payment recorded: ₦{amount:,.2f}',
            message=f'Payment of ₦{amount:,.2f} has been recorded for {student}.',
            reference=f'payment-record:{payment.id}',
            url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
        )
        messages.success(request, f'Payment of ₦{amount:,.2f} recorded.')
        return redirect('school_admin:student_detail', pk=student.pk)
