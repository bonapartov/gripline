"""Панель «Пульт Gripline» на главной странице админки (Wagtail construct_homepage_panels)."""
from django.utils import timezone
from wagtail.admin.ui.components import Component

from . import data, health


class DashboardPanel(Component):
    name = 'gripline_dashboard'
    template_name = 'dashboard/panel.html'
    order = 5  # выше стандартных панелей Wagtail (последние правки — 250)

    def get_context_data(self, parent_context):
        context = super().get_context_data(parent_context)
        request = parent_context['request']
        now = timezone.now()

        period = request.GET.get('dash', 'visit')
        if period not in dict(data.PERIODS):
            period = 'visit'
        visit_since = data.touch_visit(request.user, now)
        since = data.window_start(period, visit_since, now)

        checks = health.collect_health(now)
        level = health.worst_level(checks)
        context.update({
            'request': request,
            'attention': data.attention_items(now),
            'news': data.news_since(since),
            'news_since': timezone.localtime(since),
            'periods': data.PERIODS,
            'period': period,
            'health': checks,
            'health_level': level,
            'health_icon': health.LEVEL_ICON[level],
            'rating': data.rating_block(now),
            'summary': data.site_summary(),
            'feedback_stats': None,
        })
        if request.user.has_perm('website.view_feedback'):
            from website.feedback import stats
            context['feedback_stats'] = stats.compute_stats(30, now)
        return context
