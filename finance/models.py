from decimal import Decimal
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel
from accounts.models import Roles


class Project(TenantScopedModel):
    """A capital project or initiative with a budget target."""

    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", _("Proposed")
        APPROVED = "APPROVED", _("Approved")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")

    name = models.CharField(max_length=255, verbose_name=_("name"))
    description = models.TextField(blank=True, verbose_name=_("description"))
    target_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name=_("target amount"),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROPOSED,
        verbose_name=_("status"),
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("start date"),
    )
    target_end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("target end date"),
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="projects",
        verbose_name=_("created by"),
    )

    class Meta:
        verbose_name = _("project")
        verbose_name_plural = _("projects")
        ordering = ["-start_date", "name"]

    def __str__(self):
        return self.name

    @property
    def spent(self):
        """Sum of all Expenditure.amount related to this project."""
        result = self.expenditures.aggregate(
            total=models.Sum("amount")
        )["total"]
        return result or Decimal("0.00")

    @property
    def remaining(self):
        """Target amount minus total spent."""
        return self.target_amount - self.spent


class ExpenditureCategory(TenantScopedModel):
    """A category label for expenditures (e.g. 'Utilities', 'Maintenance')."""

    name = models.CharField(max_length=200, verbose_name=_("name"))

    class Meta:
        verbose_name = _("expenditure category")
        verbose_name_plural = _("expenditure categories")
        unique_together = ("school", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Expenditure(TenantScopedModel):
    """A single expenditure / expense transaction."""

    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenditures",
        verbose_name=_("project"),
    )
    category = models.ForeignKey(
        ExpenditureCategory,
        on_delete=models.PROTECT,
        related_name="expenditures",
        verbose_name=_("category"),
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name=_("amount"),
    )
    description = models.CharField(
        max_length=500,
        verbose_name=_("description"),
    )
    date = models.DateField(verbose_name=_("date"))
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="recorded_expenditures",
        verbose_name=_("recorded by"),
    )

    class Meta:
        verbose_name = _("expenditure")
        verbose_name_plural = _("expenditures")
        ordering = ["-date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=Decimal("0.01")),
                name="expenditure_amount_positive",
            ),
        ]

    def __str__(self):
        proj = f" ({self.project.name})" if self.project_id else ""
        return f"{self.description}: {self.amount}{proj}"
