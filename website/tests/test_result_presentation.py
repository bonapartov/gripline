import pytest
from django.template.loader import render_to_string
from wagtail.models import Locale, Page, Site
from website.models import Driver, EventPage, RaceClass, RaceClassResultGroup, RaceResult


@pytest.mark.parametrize('position,status,label', [(1,'','1'), (3,'DNF','3'),
    (0,'DNS','DNS'), (1,'DQ','DQ'), (0,'DNF','DNF'), (0,'','—')])
def test_result_display_position(position, status, label):
    result = RaceResult(position=position, final_status=status)
    assert result.display_position == label


@pytest.mark.django_db
def test_dns_and_dq_follow_classified_results_in_event_and_mini_table():
    Locale.objects.get_or_create(language_code='ru')
    root = Page.get_first_root_node() or Page.add_root(title='Root', slug='root')
    Site.objects.create(hostname='testserver', root_page=root, is_default_site=True)
    event = root.add_child(instance=EventPage(title='Presentation event', slug='presentation'))
    group = RaceClassResultGroup.objects.create(page=event, race_class=RaceClass.objects.create(name='Mini'))
    rows = []
    for name, position, status, points in [('DNS pilot',0,'DNS',0), ('Winner',1,'',0),
            ('DNF classified',2,'DNF',0), ('DQ pilot',1,'DQ',99)]:
        driver = Driver.objects.create(first_name=name,last_name='Synthetic')
        rows.append(RaceResult.objects.create(group=group,driver=driver,position=position,final_status=status,points=points))
    expected = [rows[1].pk, rows[2].pk, rows[3].pk, rows[0].pk]
    assert list(group.sorted_results().values_list('pk', flat=True)) == expected
    # The mini-table has no points ordering; both unclassified rows must still follow finishers.
    mini = list(event.race_results)
    assert [r.pk for r in mini[:2]] == expected[:2]
    html = render_to_string('includes/event_results_mini_table.html', {'results':mini})
    assert 'DNS' in html and 'DQ' in html
    assert html.index('Winner Synthetic') < html.index('DNS pilot Synthetic')
