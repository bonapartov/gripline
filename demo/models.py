from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class DemoSlot(models.Model):
    SLOT_TYPE_CHOICES = [
        ('organizer', 'Организатор'),
        ('pilot', 'Пилот'),
        ('team', 'Команда'),
    ]
    slot_type = models.CharField(max_length=20, choices=SLOT_TYPE_CHOICES)
    slot_number = models.IntegerField()
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='demo_slot')
    is_occupied = models.BooleanField(default=False)
    occupied_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('slot_type', 'slot_number')]
        ordering = ['slot_type', 'slot_number']
        verbose_name = 'Демо-слот'
        verbose_name_plural = 'Демо-слоты'

    def __str__(self):
        status = 'занят' if self.is_occupied else 'свободен'
        return f"Demo {self.get_slot_type_display()} #{self.slot_number} ({status})"

    def is_free(self):
        if not self.is_occupied:
            return True
        if self.occupied_until and timezone.now() > self.occupied_until:
            self.is_occupied = False
            self.occupied_until = None
            self.save(update_fields=['is_occupied', 'occupied_until'])
            return True
        return False

    def occupy(self):
        self.is_occupied = True
        self.occupied_until = timezone.now() + timedelta(hours=2)
        self.save(update_fields=['is_occupied', 'occupied_until'])

    def release(self):
        self.is_occupied = False
        self.occupied_until = None
        self.save(update_fields=['is_occupied', 'occupied_until'])
