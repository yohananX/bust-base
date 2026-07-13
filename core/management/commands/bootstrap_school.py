from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import School
from accounts.models import User, Roles


class Command(BaseCommand):
    help = 'Create a School and superuser atomically (bootstrap a new tenant).'

    def add_arguments(self, parser):
        parser.add_argument('--school-name', required=True)
        parser.add_argument('--username', required=True)
        parser.add_argument('--email', required=True)
        parser.add_argument('--password', required=True)

    @transaction.atomic
    def handle(self, *args, **opts):
        school = School.objects.create(
            name=opts['school_name'],
            short_code=opts['school_name'].lower().replace(' ', '-'),
        )
        User.objects.create_superuser(
            username=opts['username'],
            email=opts['email'],
            password=opts['password'],
            school=school,
            role=Roles.ADMIN,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created school '{school.name}' and superuser '{opts['username']}'"
            )
        )
