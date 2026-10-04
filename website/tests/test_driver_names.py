from django.test import TestCase

from website.import_utils import find_drivers
from website.models import Driver
from website.services.driver_names import clean_name, find_drivers_by_name, name_key


# «Ленcкий» с латинской «c» (как в протоколе РАФ) — собираем явно, чтобы тест не зависел от кодировки файла
LATIN_LENSKY = "Лен" + chr(0x63) + "кий"


class CleanNameTests(TestCase):
    def test_latin_lookalike_inside_cyrillic_word_is_replaced(self):
        # «c» в слове — латинская
        self.assertEqual(clean_name(LATIN_LENSKY), "Ленский")
        self.assertTrue(all(ord(ch) > 127 for ch in clean_name(LATIN_LENSKY)))

    def test_purely_latin_word_is_left_alone(self):
        self.assertEqual(clean_name("Anton"), "Anton")

    def test_hyphen_and_spaces_are_kept(self):
        self.assertEqual(clean_name("  Владислав-Ричард  "), "Владислав-Ричард")
        self.assertEqual(clean_name("Анна   Мария"), "Анна Мария")

    def test_yo_is_not_changed_by_clean_name(self):
        self.assertEqual(clean_name("Артём"), "Артём")


class NameKeyTests(TestCase):
    def test_e_and_yo_are_equal(self):
        self.assertEqual(name_key("Артем"), name_key("Артём"))
        self.assertEqual(name_key("Журавлёв"), name_key("журавлев"))

    def test_i_and_short_i_are_not_merged(self):
        self.assertNotEqual(name_key("Андрей"), name_key("Андреи"))

    def test_hyphen_is_not_ignored(self):
        self.assertNotEqual(name_key("Анна-Мария"), name_key("АннаМария"))


class FindDriversTests(TestCase):
    def setUp(self):
        self.artyom = Driver.objects.create(first_name="Артём", last_name="Черкозьянов")
        self.zhur = Driver.objects.create(first_name="Семён", last_name="Журавлёв")

    def test_import_name_without_yo_finds_driver_with_yo(self):
        drivers, selected = find_drivers("Артем", "Черкозьянов")
        self.assertEqual([d.id for d in drivers], [self.artyom.id])
        self.assertEqual(selected, self.artyom.id)

    def test_surname_without_yo_finds_driver(self):
        drivers, selected = find_drivers("Семен", "Журавлев")
        self.assertEqual(selected, self.zhur.id)

    def test_import_name_with_yo_finds_driver_stored_without_yo(self):
        d = Driver.objects.create(first_name="Фёдор", last_name="Зименко")
        Driver.objects.filter(id=d.id).update(first_name="Федор")
        _, selected = find_drivers("Фёдор", "Зименко")
        self.assertEqual(selected, d.id)

    def test_latin_c_in_import_still_finds_driver(self):
        d = Driver.objects.create(first_name="Кирилл", last_name="Ленский")
        _, selected = find_drivers("Кирилл", LATIN_LENSKY)
        self.assertEqual(selected, d.id)

    def test_unknown_driver_not_found(self):
        self.assertEqual(find_drivers("Иван", "Неизвестный"), ([], None))

    def test_two_matches_are_not_auto_selected(self):
        Driver.objects.create(first_name="Артем", last_name="Черкозьянов")
        drivers, selected = find_drivers("Артем", "Черкозьянов")
        self.assertEqual(len(drivers), 2)
        self.assertIsNone(selected)

    def test_two_matches_resolved_by_city(self):
        Driver.objects.filter(id=self.artyom.id).update(city="Москва")
        Driver.objects.create(first_name="Артем", last_name="Черкозьянов", city="Казань")
        _, selected = find_drivers("Артем", "Черкозьянов", "москва")
        self.assertEqual(selected, self.artyom.id)

    def test_find_drivers_by_name_returns_empty_for_blank(self):
        self.assertEqual(find_drivers_by_name("", "Журавлев"), [])
