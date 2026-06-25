import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../config.dart';

final _baseUrl = AppConfig.baseUrl;
const _tokenKey = 'auth_token';

final secureStorageProvider = Provider((_) => const FlutterSecureStorage());

final dioProvider = Provider<Dio>((ref) {
  final dio = Dio(BaseOptions(
    baseUrl: _baseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 15),
  ));

  dio.interceptors.add(InterceptorsWrapper(
    onRequest: (options, handler) async {
      final storage = ref.read(secureStorageProvider);
      final token = await storage.read(key: _tokenKey);
      if (token != null) {
        options.headers['Authorization'] = 'Bearer $token';
      }
      handler.next(options);
    },
    onError: (error, handler) {
      handler.next(error);
    },
  ));

  return dio;
});

class ApiClient {
  final Dio _dio;
  const ApiClient(this._dio);

  Future<String> login(String username, String password) async {
    final response = await _dio.post(
      '/auth/login',
      data: {'username': username, 'password': password},
      options: Options(contentType: 'application/x-www-form-urlencoded'),
    );
    return response.data['access_token'] as String;
  }

  Future<Map<String, dynamic>> getMe() async {
    final response = await _dio.get('/pilot/me');
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getPilotProfile() async {
    final response = await _dio.get('/pilot/profile');
    return response.data as Map<String, dynamic>;
  }
}

final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(ref.watch(dioProvider)),
);
