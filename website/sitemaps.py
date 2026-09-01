"""
Django Sitemap для /balance/ — не Wagtail-страница, поэтому в стандартный
Wagtail-sitemap (wagtail.contrib.sitemaps.sitemap_generator.Sitemap, строит
дерево из Page.objects.live().public()) не попадает автоматически, вопреки
формулировке ТЗ «Wagtail генерирует штатно, /balance/ попадает автоматически»
— проверено: coderedcms.urls монтирует именно этот Page-only sitemap без
параметров. Подключается вручную рядом с ним в mysite/urls.py, через тот же
sitemaps={...} механизм, что поддерживает wagtail.contrib.sitemaps.views.sitemap.
"""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class BalanceSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        # Только лендинг/калькулятор — единственная публично индексируемая
        # страница инструмента (ТЗ 9.1). Личные сетапы/карты (Блок 3) сюда
        # не попадут никогда — у них noindex, добавлять их в sitemap было бы
        # прямым противоречием собственному правилу индексации.
        return ["balance:home"]

    def location(self, item):
        return reverse(item)
