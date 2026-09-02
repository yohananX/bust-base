from decimal import Decimal
from django.contrib import admin, messages
from django.shortcuts import render
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponseRedirect

from .models import (
    FeeCategory, FeeCategoryGroup, FeeCategoryGroupAssignment,
    FeeStructure, FeePrice, FeePriceOverride, Invoice, InvoiceLineItem, Payment, PaymentLineItem,
    InvoiceResetLog, FeeValidationError,
)


# ─── Inlines ─────────────────────────────────────────────────────────────────


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ['category', 'amount', 'term', 'session', 'billing_cycle']
    can_delete = False
    max_num = 0

    def has_add_permission(self, request, obj=None):
        return False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ['amount', 'method', 'reference', 'status', 'paid_on', 'recorded_by']
    can_delete = False
    max_num = 0

    def has_add_permission(self, request, obj=None):
        return False


# ─── Custom List Filter for Invoice Status ─────────────────────────────────


class InvoiceStatusListFilter(admin.SimpleListFilter):
    title = _('status')
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [
            ('PAID', _('Paid')),
            ('PARTIAL', _('Partial')),
            ('UNPAID', _('Unpaid')),
        ]

    def queryset(self, request, queryset):
        from .selectors import invoices_with_balance

        value = self.value()
        qs = invoices_with_balance(queryset)
        if value == 'PAID':
            return qs.filter(balance_annotated__lte=Decimal('0.00'))
        elif value == 'PARTIAL':
            return qs.filter(
                balance_annotated__gt=Decimal('0.00'),
                amount_paid_annotated__gt=Decimal('0.00'),
            )
        elif value == 'UNPAID':
            return qs.filter(amount_paid_annotated__lte=Decimal('0.00'))
        return queryset


# ─── FeeCategoryGroup Admin ──────────────────────────────────────────────────


@admin.register(FeeCategoryGroup)
class FeeCategoryGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'group_type', 'school', 'is_active', 'parent']
    list_filter = ['group_type', 'is_active', 'school']
    search_fields = ['name']


@admin.register(FeeCategoryGroupAssignment)
class FeeCategoryGroupAssignmentAdmin(admin.ModelAdmin):
    list_display = ['group', 'category', 'school']
    list_filter = ['group', 'school']
    search_fields = ['category__name', 'group__name']


# ─── FeeCategory Admin ───────────────────────────────────────────────────────


@admin.register(FeeCategory)
class FeeCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'compulsory_badge', 'billing_cycle', 'student_type', 'group', 'school']
    list_filter = ['is_compulsory', 'billing_cycle', 'student_type', 'group', 'school']
    search_fields = ['name']

    @admin.display(description=_('Compulsory'))
    def compulsory_badge(self, obj):
        if obj.is_compulsory:
            return format_html('<span style="color: #b45309; font-weight: bold;">Compulsory</span>')
        return format_html('<span style="color: #2563eb; font-weight: bold;">Optional</span>')


# ─── FeeStructure Admin (DEPRECATED — kept readable for one release) ─────────


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ['scope', 'school_class', 'term', 'category', 'amount', 'student_type', 'is_recurring_override', 'deprecated', 'school']
    list_filter = ['scope', 'school_class', 'term', 'category', 'student_type', 'deprecated', 'school']
    search_fields = ['school_class__name', 'category__name']
    readonly_fields = ['deprecated', 'scope', 'school_class', 'term', 'category', 'amount', 'student_type', 'is_recurring_override', 'school']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        from django.contrib import messages
        if not request.session.get('feestructure_deprecation_warned'):
            messages.warning(
                request,
                'FeeStructure is deprecated. Use FeePrice for new pricing.',
            )
            request.session['feestructure_deprecation_warned'] = True
        return super().get_queryset(request)


@admin.register(FeePrice)
class FeePriceAdmin(admin.ModelAdmin):
    list_display = ['scope', 'school_class', 'level', 'term', 'category', 'amount', 'student_type', 'is_active', 'effective_from', 'effective_to', 'school']
    list_filter = ['scope', 'school_class', 'level', 'term', 'category', 'student_type', 'is_active', 'school']
    search_fields = ['school_class__name', 'level', 'category__name']
    readonly_fields = ['school']
    
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.pk:
            return self.readonly_fields + ['scope']
        return self.readonly_fields


@admin.register(FeePriceOverride)
class FeePriceOverrideAdmin(admin.ModelAdmin):
    list_display = ['student', 'category', 'amount', 'valid_from', 'valid_to', 'is_active', 'school']
    list_filter = ['category', 'is_active', 'school']
    search_fields = ['student__user__username', 'student__user__first_name', 'student__user__last_name', 'category__name']
    readonly_fields = ['school']


# ─── Invoice Admin ───────────────────────────────────────────────────────────


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['student', 'term', 'total_amount', 'invoice_status', 'invoice_balance', 'generated_on']
    list_filter = ['term', InvoiceStatusListFilter]
    search_fields = ['student__user__username', 'student__user__first_name', 'student__user__last_name']
    readonly_fields = ['total_amount', 'generated_on']
    inlines = [InvoiceLineItemInline, PaymentInline]
    actions = [
        'generate_invoices_for_term',
        'reset_invoices_for_term',
        'reset_invoices_for_class',
        'reset_invoices_for_student',
        'validate_invoices',
    ]

    @admin.display(description=_('Status'))
    def invoice_status(self, obj):
        status = obj.status
        if status == 'PAID':
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', status)
        elif status == 'PARTIAL':
            return format_html('<span style="color: orange; font-weight: bold;">{}</span>', status)
        return format_html('<span style="color: red; font-weight: bold;">{}</span>', status)

    @admin.display(description=_('Balance'))
    def invoice_balance(self, obj):
        return obj.balance

    @admin.action(description=_('Generate invoices for term'))
    def generate_invoices_for_term(self, request, queryset):
        """Generate invoices for all active students for selected terms."""
        from django.contrib.admin import helpers
        from .generation import generate_invoices_for_term

        if 'apply' in request.POST:
            term_id = request.POST.get('term')
            if not term_id:
                self.message_user(request, _('Please select a term.'), level=messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

            from core.models import Term

            try:
                term = Term.objects.get(pk=term_id)
            except Term.DoesNotExist:
                self.message_user(request, _('Selected term not found.'), level=messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

            generated, skipped = generate_invoices_for_term(term.school, term)

            msg = _('Generated {} invoice(s). {} skipped (already existed or no current enrollment).').format(
                generated, skipped
            )
            self.message_user(request, msg, level=messages.SUCCESS)
            return HttpResponseRedirect(request.get_full_path())

        # Get the schools from the selected invoices (or all if empty)
        schools = set()
        for invoice in queryset:
            schools.add(invoice.school)
        if not schools:
            self.message_user(request, _('No invoices selected.'), level=messages.WARNING)
            return HttpResponseRedirect(request.get_full_path())

        # Get terms for the school
        from core.models import Term
        school = list(schools)[0]  # Use first school
        terms = Term.objects.filter(school=school, is_current=True)

        context = {
            'title': _('Generate invoices for term'),
            'queryset': queryset,
            'terms': terms,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
            'media': self.media,
        }
        return render(request, 'admin/fees/generate_invoices.html', context)

    @admin.action(description=_('Reset invoices for term'))
    def reset_invoices_for_term(self, request, queryset):
        from .reset import InvoiceResetService
        from core.models import Term

        if 'apply' not in request.POST:
            terms = Term.objects.filter(school=request.user.school, is_current=True)
            context = {
                'title': _('Reset invoices for term'),
                'queryset': queryset,
                'terms': terms,
                'action_checkbox_name': request.POST.get('action_checkbox_name', ''),
                'opts': self.model._meta,
            }
            return render(request, 'admin/fees/reset_invoices_term.html', context)

        term_id = request.POST.get('term')
        reason = request.POST.get('reason', '')
        force = request.POST.get('force') == 'on'

        try:
            term = Term.objects.get(pk=term_id)
        except Term.DoesNotExist:
            self.message_user(request, _('Term not found.'), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

        if not request.user.is_superuser:
            self.message_user(request, _('Only superadmins can reset invoices.'), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

        try:
            log = InvoiceResetService.reset_term(term.school, term, user=request.user, reason=reason)
            self.message_user(
                request,
                _(f'Reset {log.scope_name}: deleted {log.invoices_deleted} invoices, '
                  f'{log.payments_deleted} payments, {log.line_items_deleted} line items.'),
                level=messages.SUCCESS,
            )
        except ValueError as e:
            self.message_user(request, str(e), level=messages.ERROR)

        return HttpResponseRedirect(request.get_full_path())

    @admin.action(description=_('Reset invoices for class'))
    def reset_invoices_for_class(self, request, queryset):
        from .reset import InvoiceResetService
        from students.models import SchoolClass
        from core.models import Term

        if 'apply' not in request.POST:
            classes = SchoolClass.objects.filter(school=request.user.school)
            terms = Term.objects.filter(school=request.user.school, is_current=True)
            context = {
                'title': _('Reset invoices for class'),
                'queryset': queryset,
                'classes': classes,
                'terms': terms,
                'action_checkbox_name': request.POST.get('action_checkbox_name', ''),
                'opts': self.model._meta,
            }
            return render(request, 'admin/fees/reset_invoices_class.html', context)

        class_id = request.POST.get('school_class')
        term_id = request.POST.get('term')
        reason = request.POST.get('reason', '')

        try:
            school_class = SchoolClass.objects.get(pk=class_id)
            term = Term.objects.get(pk=term_id)
        except (SchoolClass.DoesNotExist, Term.DoesNotExist):
            self.message_user(request, _('Invalid selection.'), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

        if not request.user.is_superuser:
            self.message_user(request, _('Only superadmins can reset invoices.'), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

        try:
            log = InvoiceResetService.reset_class(school_class.school, school_class, term, user=request.user, reason=reason)
            self.message_user(
                request,
                _(f'Reset {log.scope_name}: deleted {log.invoices_deleted} invoices.'),
                level=messages.SUCCESS,
            )
        except ValueError as e:
            self.message_user(request, str(e), level=messages.ERROR)

        return HttpResponseRedirect(request.get_full_path())

    @admin.action(description=_('Reset invoices for student'))
    def reset_invoices_for_student(self, request, queryset):
        from .reset import InvoiceResetService
        from core.models import Term

        if 'apply' not in request.POST:
            terms = Term.objects.filter(school=request.user.school, is_current=True)
            context = {
                'title': _('Reset invoices for student'),
                'queryset': queryset,
                'terms': terms,
                'action_checkbox_name': request.POST.get('action_checkbox_name', ''),
                'opts': self.model._meta,
            }
            return render(request, 'admin/fees/reset_invoices_student.html', context)

        term_id = request.POST.get('term')
        reason = request.POST.get('reason', '')

        try:
            term = Term.objects.get(pk=term_id)
        except Term.DoesNotExist:
            self.message_user(request, _('Term not found.'), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

        if not request.user.is_superuser:
            self.message_user(request, _('Only superadmins can reset invoices.'), level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

        total_deleted = 0
        for invoice in queryset:
            log = InvoiceResetService.reset_student(invoice.school, invoice.student, term, user=request.user, reason=reason)
            total_deleted += log.invoices_deleted

        self.message_user(
            request,
            _(f'Reset {total_deleted} student invoice(s) for {term.name}.'),
            level=messages.SUCCESS,
        )
        return HttpResponseRedirect(request.get_full_path())

    @admin.action(description=_('Validate selected invoices'))
    def validate_invoices(self, request, queryset):
        from .validation import InvoiceIntegrityValidator
        total_errors = 0
        for invoice in queryset:
            errors = InvoiceIntegrityValidator.validate_invoice(invoice)
            total_errors += len(errors)
        self.message_user(
            request,
            _(f'Validation complete: {total_errors} errors found across {queryset.count()} invoices.'),
            level=messages.SUCCESS if total_errors == 0 else messages.WARNING,
        )


@admin.register(PaymentLineItem)
class PaymentLineItemAdmin(admin.ModelAdmin):
    list_display = ['payment', 'kind', 'label', 'amount', 'category', 'term', 'session']
    list_filter = ['kind', 'term', 'session', 'category']
    search_fields = ['label', 'source_key', 'payment__reference']
    readonly_fields = ['payment', 'kind', 'label', 'amount', 'source_key', 'category', 'term', 'session', 'invoice']


@admin.register(InvoiceResetLog)
class InvoiceResetLogAdmin(admin.ModelAdmin):
    list_display = ['scope_type', 'scope_name', 'invoices_deleted', 'payments_deleted', 'reset_by', 'performed_at']
    list_filter = ['scope_type', 'performed_at', 'school']
    search_fields = ['scope_name', 'reason']
    readonly_fields = ['scope_type', 'scope_id', 'scope_name', 'reset_by', 'reason',
                       'invoices_deleted', 'payments_deleted', 'line_items_deleted',
                       'receipts_deleted', 'performed_at']


@admin.register(FeeValidationError)
class FeeValidationErrorAdmin(admin.ModelAdmin):
    list_display = ['code', 'message_short', 'is_resolved', 'resolved_by', 'created_at']
    list_filter = ['code', 'is_resolved', 'created_at', 'school']
    search_fields = ['message', 'related_object_type']
    readonly_fields = ['code', 'message', 'related_object_type', 'related_object_id', 'created_at']
    actions = ['mark_resolved']

    @admin.display(description=_('Message'))
    def message_short(self, obj):
        return obj.message[:80]

    @admin.action(description=_('Mark selected errors as resolved'))
    def mark_resolved(self, request, queryset):
        updated = queryset.update(is_resolved=True, resolved_by=request.user)
        self.message_user(request, _(f'Marked {updated} errors as resolved.'), level=messages.SUCCESS)
