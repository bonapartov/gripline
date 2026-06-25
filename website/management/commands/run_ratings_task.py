from django.core.management.base import BaseCommand
from django.core.management import call_command
from website.models import AnalyticsTask
import io
import sys
from datetime import datetime

class Command(BaseCommand):
    help = 'Run ratings update and save result to task'

    def add_arguments(self, parser):
        parser.add_argument('task_id', type=int)

    def handle(self, *args, **options):
        task_id = options['task_id']
        task = AnalyticsTask.objects.get(id=task_id)

        task.status = 'running'
        task.save()

        output = io.StringIO()
        error_output = io.StringIO()

        try:
            sys.stdout = output
            sys.stderr = error_output

            call_command('update_ratings', '--entity', 'all', '--model', 'all', '--alpha', '0.1')

            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            task.status = 'completed'
            task.output = output.getvalue()[:5000]
            task.completed_at = datetime.now()
            task.save()

        except Exception as e:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            task.status = 'failed'
            task.error = str(e)
            task.output = output.getvalue()[:5000]
            task.completed_at = datetime.now()
            task.save()
