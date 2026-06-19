import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';

// Обработчик фоновых сообщений — должен быть top-level функцией
@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  debugPrint('FCM background: ${message.messageId}');
}

class PushService {
  final FirebaseMessaging _fcm = FirebaseMessaging.instance;

  Future<void> init() async {
    // Запрос разрешения (iOS)
    await _fcm.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );

    FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

    FirebaseMessaging.onMessage.listen((message) {
      debugPrint('FCM foreground: ${message.notification?.title}');
      // TODO: показать in-app уведомление
    });

    FirebaseMessaging.onMessageOpenedApp.listen((message) {
      debugPrint('FCM tap: ${message.data}');
      // TODO: навигация по payload
    });
  }

  Future<String?> getToken() => _fcm.getToken();

  // Отправляет токен на наш FastAPI (после реализации эндпоинта)
  Future<void> sendTokenToServer(String serverToken) async {
    final deviceToken = await getToken();
    if (deviceToken == null) return;
    debugPrint('TODO: POST /push/register token=$deviceToken');
  }
}

final pushService = PushService();
