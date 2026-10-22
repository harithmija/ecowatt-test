import 'dart:io';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class EcoWattApi {
  EcoWattApi._(this._dio, this._cookieJar);

  final Dio _dio;
  final PersistCookieJar _cookieJar;
  VoidCallback? onUnauthorized;

  static Future<EcoWattApi> create() async {
    final directory = await getApplicationSupportDirectory();
    final jar = PersistCookieJar(
      storage: FileStorage('${directory.path}/http_cookies'),
    );
    final dio = Dio(
      BaseOptions(
        baseUrl: _baseUrl(),
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 30),
        headers: const {'Accept': 'application/json'},
      ),
    );
    dio.interceptors.add(CookieManager(jar));
    return EcoWattApi._(dio, jar);
  }

  static String _baseUrl() {
    const configured = String.fromEnvironment('API_BASE_URL');
    if (configured.isNotEmpty) return configured.replaceFirst(RegExp(r'/+$'), '');
    if (!kIsWeb && Platform.isAndroid) return 'http://10.0.2.2:8000';
    return 'http://127.0.0.1:8000';
  }

  Future<Map<String, dynamic>> getMap(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    final response = await _request(() => _dio.get<Object?>(
          path,
          queryParameters: query,
        ));
    return Map<String, dynamic>.from(response.data! as Map);
  }

  Future<List<dynamic>> getList(String path) async {
    final response = await _request(() => _dio.get<Object?>(path));
    return List<dynamic>.from(response.data! as List);
  }

  Future<Map<String, dynamic>> post(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final response = await _request(
      () => _dio.post<Object?>(path, data: body),
    );
    return Map<String, dynamic>.from(response.data! as Map);
  }

  Future<Response<Object?>> _request(
    Future<Response<Object?>> Function() call,
  ) async {
    try {
      return await call();
    } on DioException catch (error) {
      final status = error.response?.statusCode;
      if (status == 401) onUnauthorized?.call();
      final data = error.response?.data;
      final detail = data is Map ? data['detail'] : null;
      final message = detail is String
          ? detail
          : error.type == DioExceptionType.connectionError
              ? 'Could not reach the EcoWatt server. Check the server address and network.'
              : error.type == DioExceptionType.connectionTimeout
                  ? 'The EcoWatt server did not respond in time.'
                  : 'Request failed${status == null ? '' : ' ($status)'}.';
      throw ApiException(message, statusCode: status);
    } on TypeError {
      throw const ApiException('The server returned data in an unexpected format.');
    }
  }

  Future<void> clearCookies() async {
    await _cookieJar.deleteAll();
  }
}
