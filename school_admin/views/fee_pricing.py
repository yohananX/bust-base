"""Fee pricing CRUD and bulk operations for school admin portal."""
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from fees.models import FeeCategory, FeePrice, InvoiceLineItem
from fees.pricing import resolve_price_for_student
from students.models import SchoolClass


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
    """Edit a fee price (FeePrice)."""

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
