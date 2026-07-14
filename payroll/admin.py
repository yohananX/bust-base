from decimal import Decimal

from django.contrib import admin, messages
from django.db import models
from django.shortcuts import render
from django.urls import path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponseRedirect

from .models import (
    StaffProfile,
    PayGrade,
    AllowanceDefinition,
    DeductionDefinition,
    PayrollRun,
    Payslip,
    PayslipLineItem,
    SalaryDisbursement,
)


# ─── Inlines ─────────────────────────────────────────────────────────────────


class PayslipLineItemInline(admin.TabularInline):
    model = PayslipLineItem
    extra = 0
    readonly_fields = ['label', 'amount', 'line_type']
    can_delete = False
    max_num = 0

    def has_add_permission(self, request, obj=None):
        return False


class SalaryDisbursementInline(admin.TabularInline):
    model = SalaryDisbursement
    extra = 0
    readonly_fields = ['amount', 'method', 'reference', 'status', 'disbursed_on', 'recorded_by']
    can_delete = False
    max_num = 0

    def has_add_permission(self, request, obj=None):
        return False


# ─── Custom List Filter for Payslip Status ──────────────────────────────────


class PayslipStatusListFilter(admin.SimpleListFilter):
    title = _('disbursement status')
    parameter_name = 'disbursement_status'

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
                SalaryDisbursement.objects.filter(
                    payslip=models.OuterRef('pk'),
                    status=SalaryDisbursement.Status.CONFIRMED,
                ).values('payslip').annotate(
                    total=models.Sum('amount')
                ).values('total')[:1],
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
            return queryset.filter(net_pay__lte=paid_subq)
        elif value == 'PARTIAL':
            paid_subq = models.Subquery(
                SalaryDisbursement.objects.filter(
                    payslip=models.OuterRef('pk'),
                    status=SalaryDisbursement.Status.CONFIRMED,
                ).values('payslip').annotate(
                    total=models.Sum('amount')
                ).values('total')[:1],
                output_field=models.DecimalField(max_digits=12, decimal_places=2),
            )
            return queryset.filter(
                net_pay__gt=paid_subq,
                paid_subq__gt=Decimal('0.00'),
            )
        elif value == 'UNPAID':
            return queryset.filter(
                ~models.Exists(
                    SalaryDisbursement.objects.filter(
                        payslip=models.OuterRef('pk'),
                        status=SalaryDisbursement.Status.CONFIRMED,
                    )
                )
            )
        return queryset


# ─── StaffProfile Admin ──────────────────────────────────────────────────────


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'user_full_name', 'user_role', 'pay_grade', 'status', 'hire_date']
    list_filter = ['status', 'pay_grade', 'school']
    search_fields = ['employee_id', 'user__username', 'user__first_name', 'user__last_name']
    raw_id_fields = ['user']

    @admin.display(description=_('Name'))
    def user_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description=_('Role'))
    def user_role(self, obj):
        return obj.user.get_role_display() if hasattr(obj.user, 'get_role_display') else obj.user.role


# ─── PayGrade Admin ──────────────────────────────────────────────────────────


@admin.register(PayGrade)
class PayGradeAdmin(admin.ModelAdmin):
    list_display = ['name', 'role_filter', 'base_salary', 'school']
    list_filter = ['role_filter', 'school']


# ─── AllowanceDefinition Admin ───────────────────────────────────────────────


@admin.register(AllowanceDefinition)
class AllowanceDefinitionAdmin(admin.ModelAdmin):
    list_display = ['name', 'amount', 'is_active', 'scope', 'school']
    list_filter = ['is_active', 'school']
    search_fields = ['name']

    @admin.display(description=_('Scope'))
    def scope(self, obj):
        return str(obj.pay_grade or obj.target_staff or '—')


# ─── DeductionDefinition Admin ───────────────────────────────────────────────


@admin.register(DeductionDefinition)
class DeductionDefinitionAdmin(admin.ModelAdmin):
    list_display = ['name', 'amount', 'is_active', 'scope', 'school']
    list_filter = ['is_active', 'school']
    search_fields = ['name']

    @admin.display(description=_('Scope'))
    def scope(self, obj):
        return str(obj.pay_grade or obj.target_staff or '—')


# ─── PayrollRun Admin ────────────────────────────────────────────────────────


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = [
        'label', 'period_start', 'period_end', 'pay_date',
        'payroll_staff_count', 'payroll_total_gross', 'payroll_total_net',
        'generated_on', 'generated_by',
    ]
    list_filter = ['school']
    readonly_fields = ['generated_on', 'generated_by', 'cancelled_at']
    actions = ['generate_payroll_run']

    @admin.display(description=_('Staff'))
    def payroll_staff_count(self, obj):
        return obj.staff_count

    @admin.display(description=_('Gross Pay'))
    def payroll_total_gross(self, obj):
        return obj.total_gross_pay

    @admin.display(description=_('Net Pay'))
    def payroll_total_net(self, obj):
        return obj.total_net_pay

    @admin.action(description=_('Generate payroll run'))
    def generate_payroll_run(self, request, queryset):
        """Intermediate page action for generating a payroll run."""
        if 'apply' in request.POST:
            label = request.POST.get('label', '')
            period_start = request.POST.get('period_start', '')
            period_end = request.POST.get('period_end', '')
            pay_date = request.POST.get('pay_date', '')
            staff_filter_raw = request.POST.get('staff_filter', '')

            if not all([label, period_start, period_end, pay_date]):
                self.message_user(
                    request,
                    _('Please fill in label, period start, period end, and pay date.'),
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(request.get_full_path())

            from datetime import datetime
            from django.utils.dateparse import parse_date

            from .utils import generate_payroll_run as run_generation

            school = request.user.school
            staff_filter = None
            if staff_filter_raw:
                staff_ids = [s.strip() for s in staff_filter_raw.split(',') if s.strip()]
                if staff_ids:
                    staff_filter = StaffProfile.objects.filter(
                        school=school,
                        employee_id__in=staff_ids,
                    )

            result = run_generation(
                school=school,
                label=label,
                period_start=parse_date(period_start),
                period_end=parse_date(period_end),
                pay_date=parse_date(pay_date),
                generated_by=request.user,
                staff_filter=staff_filter,
            )

            payroll_run, counts = result
            msg = _(
                'Payroll run "{}" created. Generated {} payslip(s), skipped {}.'
            ).format(label, counts['generated'], counts['skipped'])
            self.message_user(request, msg, level=messages.SUCCESS)
            return HttpResponseRedirect(request.get_full_path())

        context = {
            'title': _('Generate Payroll Run'),
            'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
            'media': self.media,
        }
        return render(request, 'admin/payroll/generate_payroll_run.html', context)


# ─── Payslip Admin ───────────────────────────────────────────────────────────


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = [
        'staff', 'payroll_run', 'gross_pay', 'net_pay',
        'payslip_disbursement_status', 'payslip_balance',
    ]
    list_filter = ['payroll_run', PayslipStatusListFilter]
    search_fields = ['staff__user__username', 'staff__employee_id']
    readonly_fields = [
        'staff', 'payroll_run', 'base_salary', 'total_allowances',
        'total_deductions', 'gross_pay', 'net_pay',
    ]
    inlines = [PayslipLineItemInline, SalaryDisbursementInline]
    actions = ['record_disbursement']

    @admin.display(description=_('Status'))
    def payslip_disbursement_status(self, obj):
        status = obj.disbursement_status
        if status == 'PAID':
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', status)
        elif status == 'PARTIAL':
            return format_html('<span style="color: orange; font-weight: bold;">{}</span>', status)
        return format_html('<span style="color: red; font-weight: bold;">{}</span>', status)

    @admin.display(description=_('Balance'))
    def payslip_balance(self, obj):
        return obj.balance

    @admin.action(description=_('Record disbursement'))
    def record_disbursement(self, request, queryset):
        """Record salary disbursements for selected payslips."""
        if 'apply' in request.POST:
            method = request.POST.get('method', '')
            reference_base = request.POST.get('reference', '')
            disbursed_on_raw = request.POST.get('disbursed_on', '')

            if not all([method, reference_base, disbursed_on_raw]):
                self.message_user(
                    request,
                    _('Please fill in method, reference, and disbursed on date.'),
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(request.get_full_path())

            from django.utils.dateparse import parse_datetime
            from django.utils import timezone

            disbursed_on = parse_datetime(disbursed_on_raw)
            if not disbursed_on:
                self.message_user(
                    request,
                    _('Invalid date format. Use YYYY-MM-DD HH:MM:SS.'),
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(request.get_full_path())

            if timezone.is_naive(disbursed_on):
                disbursed_on = timezone.make_aware(disbursed_on)

            created_count = 0
            for payslip in queryset:
                balance = payslip.balance
                if balance <= 0:
                    continue

                reference = f'{reference_base}-{payslip.id}'
                disbursement, created = SalaryDisbursement.objects.get_or_create(
                    school=payslip.school,
                    reference=reference,
                    defaults={
                        'payslip': payslip,
                        'amount': balance,
                        'method': method,
                        'status': SalaryDisbursement.Status.CONFIRMED,
                        'disbursed_on': disbursed_on,
                        'recorded_by': request.user,
                    },
                )
                if created:
                    created_count += 1
                    # Send notification to staff member
                    from notifications.utils import notify
                    try:
                        staff_user = payslip.staff.user
                        notify(
                            recipient=staff_user,
                            channel='EMAIL',
                            subject='Salary disbursement processed',
                            message=(
                                'Your salary of NGN{amount} for {period} '
                                'has been disbursed.'
                            ).format(
                                amount=disbursement.amount,
                                period=payslip.payroll_run.label,
                            ),
                            reference='disbursement:{}'.format(disbursement.id),
                        )
                    except Exception:
                        # Notification failure should not block disbursement
                        pass

            self.message_user(
                request,
                _('Created {} disbursement(s).').format(created_count),
                level=messages.SUCCESS,
            )
            return HttpResponseRedirect(request.get_full_path())

        context = {
            'title': _('Record Disbursement'),
            'queryset': queryset,
            'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
            'media': self.media,
        }
        return render(request, 'admin/payroll/record_disbursement.html', context)


# ─── SalaryDisbursement Admin ────────────────────────────────────────────────


@admin.register(SalaryDisbursement)
class SalaryDisbursementAdmin(admin.ModelAdmin):
    list_display = ['payslip', 'amount', 'method', 'reference', 'status', 'disbursed_on', 'recorded_by']
    list_filter = ['status', 'method', 'school']
    search_fields = ['reference', 'payslip__staff__user__username']
    readonly_fields = ['disbursed_on', 'recorded_by']
