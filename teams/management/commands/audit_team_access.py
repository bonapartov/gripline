import json
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from teams.audit import audit_memberships


class Command(BaseCommand):
    help = 'Read-only/dry-run membership audit; never confirms or deactivates links.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Explicit alias; always dry-run.')
        parser.add_argument('--summary', action='store_true', help='Only aggregate counts, no link IDs.')

    def handle(self, *args, **options):
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            result = audit_memberships()
            if options['summary']:
                result.pop('memberships')
                result.pop('history_without_membership')
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
