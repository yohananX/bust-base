import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_SEND_URL = 'https://api.brevo.com/v3/smtp/email'


class BrevoEmailBackend(BaseEmailBackend):
    """Django email backend that sends via the Brevo transactional API.

    Requires BREVO_API_KEY (xkeysib-...) in the environment and a sender
    email verified in the Brevo dashboard (set via DEFAULT_FROM_EMAIL).
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = settings.BREVO_API_KEY

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            if self._send(message):
                sent += 1
        return sent

    def _send(self, message):
        payload = {
            'sender': {'email': message.from_email},
            'to': [{'email': address} for address in message.to],
            'subject': message.subject,
            'textContent': message.body,
        }
        for alternative, mimetype in getattr(message, 'alternatives', ()):
            if mimetype == 'text/html':
                payload['htmlContent'] = alternative
                break
        try:
            response = requests.post(
                BREVO_SEND_URL,
                json=payload,
                headers={'api-key': self.api_key, 'accept': 'application/json'},
                timeout=30,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            if not self.fail_silently:
                raise
            logger.error('Brevo email send failed: %s', exc)
            return False