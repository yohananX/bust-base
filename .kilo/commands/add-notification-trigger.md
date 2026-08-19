# Command: Add a Notification Trigger

Use this when the user asks to notify parents/admins about an event.

## Steps

1. Identify the event location (view, admin action, webhook handler, signal)
2. Determine recipients:
   - Parent/guardian: `student.guardian_links.filter(is_primary_contact=True).first().guardian`
   - Admin: `notify_admins(school=school, ...)` (future) or `User.objects.filter(role=Roles.ADMIN, school=school)`
   - Student: `student.user`
3. Call `notify()` with:
   - `recipient=user`
   - `channel='IN_APP'` (or EMAIL/SMS if explicitly requested)
   - `subject=...`
   - `message=...`
   - `reference='<event-type>:{id}'` for dedup
   - `url=reverse('some:url')` for deep linking (optional)
   - `action_label='Take action'` for action items (optional)

## Example: Payment confirmed

```python
from notifications.utils import notify

guardian_link = payment.student.guardian_links.filter(is_primary_contact=True).first()
if guardian_link:
    notify(
        recipient=guardian_link.guardian,
        channel='IN_APP',
        subject=f'Payment confirmed: ?{payment.amount:,.2f}',
        message=f'Payment of ?{payment.amount:,.2f} for {payment.student} has been confirmed.',
        reference=f'payment-confirm:{payment.id}',
    )
```

## Dedup References
- `payment-confirm:{payment_id}`
- `payment-fail:{payment_id}`
- `receipt:{payment_id}`
- `transfer-confirm:{payment_id}`
- `transfer-reject:{payment_id}`
- `payment-record:{payment_id}`
- `term-results:{term_id}`

## Gotchas
- Always guard with `if guardian_link:` — not every student has a primary contact
- Never notify the actor (the user who triggered the event)
- Use `notify_many()` for batch notifications to multiple recipients
- IN_APP is the default channel until email/SMS API keys are configured
