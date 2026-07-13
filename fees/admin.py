from decimal import Decimal
from django.contrib import admin, messages
from django.db import models
from django.shortcuts import render
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponseRedirect

from .models import FeeCategory, FeeStructure, Invoice, InvoiceLineItem, Payment


# ─── Inlines ─────────────────────────────────────────────────────────────────


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ['category', 'amount']
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
        value = self.value()
        if value == 'PAID':
            paid_subq = models.Subquery(
                Payment.objects.filter(
                    invoice=models.OuterRef('pk'),
                    status=Payment.Status.CONFIRMED,
                ).values('invoice').annotate(
                    total=models.Sum('amount')
                ).values('total')[:1],
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
            return queryset.filter(total_amount__lte=paid_subq)
        elif value == 'PARTIAL':
            paid_subq = models.Subquery(
                Payment.objects.filter(
                    invoice=models.OuterRef('pk'),
                    status=Payment.Status.CONFIRMED,
                ).values('invoice').annotate(
                    total=models.Sum('amount')
                ).values('total')[:1],
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
            return queryset.filter(
                total_amount__gt=paid_subq,
                paid_subq__gt=Decimal('0.00'),
            )
        elif value == 'UNPAID':
            return queryset.filter(
                ~models.Exists(
                    Payment.objects.filter(
                        invoice=models.OuterRef('pk'),
                        status=Payment.Status.CONFIRMED,
                    )
                )
            )
        return queryset


# ─── FeeCategory Admin ───────────────────────────────────────────────────────


@admin.register(FeeCategory)
class FeeCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'school']
    list_filter = ['school']
    search_fields = ['name']


# ─── FeeStructure Admin ──────────────────────────────────────────────────────


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ['school_class', 'term', 'category', 'amount', 'school']
    list_filter = ['school_class', 'term', 'category', 'school']
    search_fields = ['school_class__name', 'category__name']


# ─── Invoice Admin ───────────────────────────────────────────────────────────


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['student', 'term', 'total_amount', 'invoice_status', 'invoice_balance', 'generated_on']
    list_filter = ['term', InvoiceStatusListFilter]
    search_fields = ['student__user__username', 'student__user__first_name', 'student__user__last_name']
    readonly_fields = ['total_amount', 'generated_on']
    inlines = [InvoiceLineItemInline, PaymentInline]
    actions = ['generate_invoices_for_term']

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

        if 'apply' in request.POST:
            term_id = request.POST.get('term')
            if not term_id:
                self.message_user(request, _('Please select a term.'), level=messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

            from core.models import Term
            from students.models import Student, ClassEnrollment

            try:
                term = Term.objects.get(pk=term_id)
            except Term.DoesNotExist:
                self.message_user(request, _('Selected term not found.'), level=messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

            generated = 0
            skipped_already = 0
            skipped_inactive = 0

            students = Student.objects.filter(
                school=term.school,
                status=Student.ACTIVE,
                enrollments__session=term.session,
                enrollments__is_current=True,
            ).distinct()

            for student in students:
                if Invoice.objects.filter(school=term.school, student=student, term=term).exists():
                    skipped_already += 1
                    continue

                enrollment = ClassEnrollment.objects.filter(
                    student=student,
                    session=term.session,
                    is_current=True,
                ).first()
                if not enrollment:
                    skipped_inactive += 1
                    continue

                fee_structures = FeeStructure.objects.filter(
                    school=term.school,
                    school_class=enrollment.school_class,
                    term=term,
                )

                if not fee_structures.exists():
                    continue

                line_items_data = []
                total = Decimal('0.00')
                for fs in fee_structures:
                    line_items_data.append({
                        'category': fs.category,
                        'amount': fs.amount,
                    })
                    total += fs.amount

                invoice = Invoice.objects.create(
                    school=term.school,
                    student=student,
                    term=term,
                    total_amount=total,
                )

                for li in line_items_data:
                    InvoiceLineItem.objects.create(
                        invoice=invoice,
                        category=li['category'],
                        amount=li['amount'],
                    )

                generated += 1

            msg = _('Generated {} invoice(s). {} already existed (skipped). {} students without current enrollment (skipped).').format(
                generated, skipped_already, skipped_inactive
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
