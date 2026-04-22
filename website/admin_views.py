from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.management import call_command
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from website.models import Driver, Chassis, RaceResult, UpdateLog
import io
import sys
import datetime

@staff_member_required
def analytics_dashboard(request):
    context = {}

    # Реальная статистика из базы данных
    context['total_pilots'] = Driver.objects.count()
    context['total_chassis'] = Chassis.objects.count()
    context['total_races'] = RaceResult.objects.count()

    # Последнее обновление из лога
    last_log = UpdateLog.objects.first()
    if last_log:
        context['last_update'] = timezone.localtime(last_log.updated_at).strftime('%d.%m.%Y %H:%M')
        context['last_status'] = last_log.status
    else:
        context['last_update'] = '—'

    if request.method == 'POST':
        # Буфер для перехвата вывода команды
        output = io.StringIO()
        error_output = io.StringIO()

        try:
            # Перенаправляем stdout/stderr
            sys.stdout = output
            sys.stderr = error_output

            # Запускаем обновление всех моделей
            call_command('update_ratings', '--entity', 'all', '--model', 'all', '--alpha', '0.1')

            # Возвращаем stdout/stderr обратно
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            context['success'] = True
            context['output'] = output.getvalue()

            # Записываем успешное обновление в лог
            UpdateLog.objects.create(
                status='success',
                message=output.getvalue()[:500]  # обрезаем, чтобы не забивать базу
            )

            messages.success(request, "✅ Все рейтинги успешно обновлены!")

        except Exception as e:
            # Возвращаем stdout/stderr обратно в случае ошибки
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            context['error'] = True
            context['error_message'] = str(e)
            context['error_output'] = error_output.getvalue()
            context['output'] = output.getvalue()

            # Записываем ошибку в лог
            UpdateLog.objects.create(
                status='error',
                message=f"Ошибка: {str(e)}\n\n{error_output.getvalue()}"
            )

            messages.error(request, f"❌ Ошибка при обновлении: {str(e)}")

    return render(request, 'admin/analytics_dashboard.html', context)
