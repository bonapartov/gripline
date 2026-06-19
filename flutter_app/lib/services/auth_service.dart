import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:dio/dio.dart';
import '../models/auth_user.dart';
import 'api_client.dart';

const _tokenKey = 'auth_token';

// Провайдер текущего авторизованного пользователя
final authStateProvider = FutureProvider<AuthUser?>((ref) async {
  final storage = ref.watch(secureStorageProvider);
  final token = await storage.read(key: _tokenKey);
  if (token == null) return null;

  try {
    final api = ref.watch(apiClientProvider);
    final data = await api.getMe();
    return AuthUser.fromJson(data, token);
  } catch (_) {
    await storage.delete(key: _tokenKey);
    return null;
  }
});

class AuthNotifier extends AsyncNotifier<AuthUser?> {
  @override
  Future<AuthUser?> build() async {
    return ref.watch(authStateProvider.future);
  }

  Future<void> login(String username, String password) async {
    state = const AsyncLoading();
    try {
      final api = ref.read(apiClientProvider);
      final storage = ref.read(secureStorageProvider);

      final token = await api.login(username, password);
      await storage.write(key: _tokenKey, value: token);

      final data = await api.getMe();
      state = AsyncData(AuthUser.fromJson(data, token));
    } on DioException catch (e) {
      final msg = e.response?.data?['detail'] ?? 'Ошибка соединения';
      state = AsyncError(msg, StackTrace.current);
    } catch (e) {
      state = AsyncError(e.toString(), StackTrace.current);
    }
  }

  Future<void> logout() async {
    final storage = ref.read(secureStorageProvider);
    await storage.delete(key: _tokenKey);
    state = const AsyncData(null);
  }
}

final authNotifierProvider = AsyncNotifierProvider<AuthNotifier, AuthUser?>(
  AuthNotifier.new,
);
