// Конфигурация приложения
// Перед релизом замени baseUrl на продакшн-адрес

class AppConfig {
  // Локальная разработка: 10.0.2.2 — это localhost хоста из Android-эмулятора
  // iOS-симулятор: 127.0.0.1
  // Реальное устройство: IP вашего компьютера в локальной сети
  static const String baseUrl = 'http://10.0.2.2:8001';

  static const String appName = 'Gripline';
  static const String appVersion = '1.0.0';
}
