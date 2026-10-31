"""Historical membership inference is disabled. Run the read-only audit instead."""
def run():
    from django.core.management import call_command
    call_command('audit_team_access')

if __name__ == '__main__':
    run()
