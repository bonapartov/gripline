import json
import os
import subprocess
import sys
import tempfile
import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from website.models import Driver, Chassis, RaceResult, UpdateLog


_TASK_FILE = os.path.join(tempfile.gettempdir(), 'analytics_task.json')
_LOG_FILE = os.path.join(tempfile.gettempdir(), 'analytics_task.log')


def _read_task():
    try:
        with open(_TASK_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _write_task(data):
    with open(_TASK_FILE, 'w') as f:
        json.dump(data, f)


def _is_process_running(pid):
    """Проверяет жив ли процесс (не зомби и не завершён)."""
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('State:'):
                    # Z = zombie (процесс завершился, но не прибран)
                    return 'Z' not in line
        return False
    except (FileNotFoundError, PermissionError):
        return False


@staff_member_required
def analytics_dashboard(request):
    context = {
        'total_pilots': Driver.objects.count(),
        'total_chassis': Chassis.objects.count(),
        'total_races': RaceResult.objects.count(),
    }

    last_log = UpdateLog.objects.first()
    if last_log:
        context['last_update'] = timezone.localtime(last_log.updated_at).strftime('%d.%m.%Y %H:%M')
        context['last_status'] = last_log.status
    else:
        context['last_update'] = '—'

    if request.method == 'POST':
        task = _read_task()
        if task and task.get('running') and _is_process_running(task.get('pid', 0)):
            return JsonResponse({'error': 'Обновление уже запущено'}, status=400)

        open(_LOG_FILE, 'w').close()

        python = sys.executable
        manage_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'manage.py'
        )

        proc = subprocess.Popen(
            [python, manage_py, 'update_all_analytics', '--entity', 'all', '--model', 'all'],
            stdout=open(_LOG_FILE, 'w'),
            stderr=subprocess.STDOUT,
            close_fds=True,
        )

        _write_task({'pid': proc.pid, 'running': True, 'started': datetime.datetime.now().isoformat()})

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'started': True, 'pid': proc.pid})

    return render(request, 'admin/analytics_dashboard.html', context)


@staff_member_required
def analytics_status(request):
    task = _read_task()

    if not task:
        return JsonResponse({'running': False, 'lines': [], 'done': True})

    try:
        with open(_LOG_FILE) as f:
            lines = f.read().splitlines()
    except Exception:
        lines = []

    running = False
    if task.get('running'):
        pid = task.get('pid', 0)
        running = _is_process_running(pid)

        if not running:
            log_text = '\n'.join(lines)
            status = 'error' if any('Error' in l or 'Traceback' in l for l in lines) else 'success'
            UpdateLog.objects.create(status=status, message=log_text[:500])
            _write_task({'pid': pid, 'running': False})

    return JsonResponse({'running': running, 'lines': lines, 'done': not running})
