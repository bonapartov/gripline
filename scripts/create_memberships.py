"""Populate roster from results without granting private-data access.

Read-only by default. Applying is an explicit maintenance action, not a rating
recalculation or confirmation of access. Never executed on production in this task.
"""
def run(apply=False):
    from website.models import RaceResult
    from teams.access import record_team_membership
    pairs = RaceResult.objects.filter(team__isnull=False, driver__isnull=False).order_by().values_list(
        'driver_id', 'team_id').distinct()
    if not apply:
        return list(pairs)
    for driver_id, team_id in pairs:
        record_team_membership(driver_id, team_id)

if __name__ == '__main__':
    print(run())
