from wagtail.snippets.models import register_snippet
from .models import TeamClaim, TeamManager, TeamJoinRequest

# Простая регистрация без кастомных настроек
register_snippet(TeamClaim)
register_snippet(TeamManager)
register_snippet(TeamJoinRequest)
