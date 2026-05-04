import 'package:flutter/foundation.dart';

class LoggerService {
  static LoggerService? _instance;
  static LoggerService get instance => _instance ??= LoggerService._internal();
  
  LoggerService._internal();
  
  bool _isDebugEnabled = true;
  bool get isDebugEnabled => _isDebugEnabled;
  
  void setDebugEnabled(bool enabled) {
    _isDebugEnabled = enabled;
  }
  
  void info(String message, {String? tag, dynamic error, StackTrace? stackTrace}) {
    if (_isDebugEnabled) {
      _log('INFO', message, tag: tag, error: error, stackTrace: stackTrace);
    }
  }
  
  void warning(String message, {String? tag, dynamic error, StackTrace? stackTrace}) {
    if (_isDebugEnabled) {
      _log('WARNING', message, tag: tag, error: error, stackTrace: stackTrace);
    }
  }
  
  void error(String message, {String? tag, dynamic error, StackTrace? stackTrace}) {
    if (_isDebugEnabled) {
      _log('ERROR', message, tag: tag, error: error, stackTrace: stackTrace);
    }
  }
  
  void debug(String message, {String? tag, dynamic error, StackTrace? stackTrace}) {
    if (_isDebugEnabled) {
      _log('DEBUG', message, tag: tag, error: error, stackTrace: stackTrace);
    }
  }
  
  void _log(String level, String message, {String? tag, dynamic error, StackTrace? stackTrace}) {
    final timestamp = DateTime.now().toIso8601String();
    final tagString = tag != null ? ' [$tag]' : '';
    final errorString = error != null ? ' Error: $error' : '';
    final stackTraceString = stackTrace != null ? '\n$stackTrace' : '';
    
    final logMessage = '[$timestamp] [$level]$tagString: $message$errorString$stackTraceString';
    
    if (kDebugMode) {
      debugPrint(logMessage);
    }
    
    // Ici, vous pourriez envoyer les logs à un service de logging distant
    // par exemple, Sentry, Firebase Crashlytics, etc.
  }
}