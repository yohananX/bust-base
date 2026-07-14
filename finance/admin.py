from decimal import Decimal
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Project, ExpenditureCategory, Expenditure


# ─── Project Admin ────────────────────────────────────────────────────────

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = [
        "name", "project_spent", "project_remaining", "target_amount",
        "status", "start_date", "created_by",
    ]
    list_filter = ["status", "school"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_by"]
    raw_id_fields = ["created_by"]

    @admin.display(description=_("Spent"))
    def project_spent(self, obj):
        return obj.spent

    @admin.display(description=_("Remaining"))
    def project_remaining(self, obj):
        remaining = obj.remaining
        if remaining < 0:
            return format_html(
                '<span style="color: red; font-weight: bold;">{}</span>',
                remaining,
            )
        return remaining


# ─── ExpenditureCategory Admin ────────────────────────────────────────────

@admin.register(ExpenditureCategory)
class ExpenditureCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "school"]
    list_filter = ["school"]
    search_fields = ["name"]


# ─── Expenditure Admin ───────────────────────────────────────────────────

@admin.register(Expenditure)
class ExpenditureAdmin(admin.ModelAdmin):
    list_display = ["description", "amount", "category", "project", "date", "recorded_by"]
    list_filter = ["category", "project", "date", "school"]
    search_fields = ["description"]
    date_hierarchy = "date"
    raw_id_fields = ["project", "recorded_by"]
