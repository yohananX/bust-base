"""Audit trail for critical records.

Records CREATE / UPDATE / DELETE events for the financially and academically
significant models (payments, invoices, scores, payslips, disbursements) into
``AuditLog`` — including who (the current request user, tracked via
``CurrentUserMiddleware``) and what changed (field diffs, or a full snapshot
on delete).

Deliberately conservative:

- only the models in ``WATCHED_MODELS`` are watched;
- unchanged saves produce no log row (the diff is empty);
- ``bulk_update()`` and ``queryset.update()`` bypass Django signals and are
  therefore not audited (score grids enter data through bulk paths) — a
  documented trade-off of the signals approach.
"""
import threading
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import AuditLog

WATCHED_MODELS = {
    'fees.payment': 'Payment',
    'fees.invoice': 'Invoice',
    'academics.score': 'Score',
    'payroll.payslip': 'Payslip',
    'payroll.salarydisbursement': 'SalaryDisbursement',
}

_local = threading.local()


def set_current_user(user):
    """Record the active request user for audit logging (thread-local)."""
    _local.user = user


def get_current_user():
    """Return the active request user, or None outside a request cycle."""
    return getattr(_local, 'user', None)


def _jsonable(value):
    """Coerce a model field value into something JSONField can store."""
    if isinstance(value, models.Model):
        return value.pk
    if isinstance(value, models.fields.files.FieldFile):
        return value.name if value else None
    return value


def _snapshot(instance):
    """JSON-safe snapshot of all concrete fields (excluding the PK).

    FK fields are read from their raw ``_id`` attribute so cascade-deleted
    related objects do not raise ``DoesNotExist`` during ``post_delete``.
    """
    changes = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key:
            continue
        if field.is_relation and field.many_to_one:
            value = getattr(instance, field.attname)
        else:
            try:
                value = getattr(instance, field.name)
            except ObjectDoesNotExist:
                value = None
        changes[field.name] = _jsonable(value)
    return changes


def _write_log(instance, action, changes):
    actor = get_current_user()
    AuditLog.objects.create(
        school=instance.school,
        actor=actor if actor and actor.is_authenticated else None,
        model_name=instance.__class__.__name__,
        object_id=str(instance.pk),
        action=action,
        summary=f'{instance.__class__.__name__} #{instance.pk} {action.lower()}',
        changes=changes or {},
    )


@receiver(pre_save)
def _capture_before_save(sender, instance, **kwargs):
    """Remember pre-save field values so post_save can diff them.

    pre_save fires after the in-memory instance was mutated, so the old
    values are re-fetched from the database (one extra query per update —
    creates skip this entirely).
    """
    if instance._meta.label_lower not in WATCHED_MODELS or instance.pk is None:
        return
    fields = [f.name for f in instance._meta.concrete_fields if not f.primary_key]
    row = sender.objects.filter(pk=instance.pk).values(*fields).first()
    if row is None:
        return
    before = getattr(_local, 'before', None)
    if before is None:
        before = {}
        _local.before = before
    before[(sender._meta.label_lower, instance.pk)] = row


def _normalise(value):
    """Treat empty strings and None as equal (FileField stores '' in DB)."""
    return None if value == '' else value


@receiver(post_save)
def _log_create_or_update(sender, instance, created, **kwargs):
    """Log CREATE events and UPDATE events that actually changed a field."""
    if instance._meta.label_lower not in WATCHED_MODELS:
        return
    if created:
        _write_log(instance, AuditLog.Action.CREATE, {})
        return
    key = (sender._meta.label_lower, instance.pk)
    before = getattr(_local, 'before', {}).pop(key, None)
    if before is None:
        return
    after = _snapshot(instance)
    diff = {
        name: [before[name], after[name]]
        for name in before
        if _normalise(before[name]) != _normalise(after[name])
    }
    if diff:
        _write_log(instance, AuditLog.Action.UPDATE, diff)


@receiver(post_delete)
def _log_delete(sender, instance, **kwargs):
    """Log DELETE events with a full snapshot so the record survives removal."""
    if instance._meta.label_lower not in WATCHED_MODELS:
        return
    _write_log(instance, AuditLog.Action.DELETE, _snapshot(instance))
