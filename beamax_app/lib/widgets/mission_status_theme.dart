import 'package:flutter/material.dart';

class MissionStatusTheme {
  MissionStatusTheme._();

  static Color colorFor(String status) {
    switch (status.toUpperCase()) {
      case 'CREATED':
        return const Color(0xFF9E9E9E);
      case 'PLANNED':
        return const Color(0xFF2196F3);
      case 'RUNNING':
        return const Color(0xFF4CAF50);
      case 'REVIEW':
        return const Color(0xFFFF9800);
      case 'DONE':
        return const Color(0xFF4CAF50);
      case 'FAILED':
        return const Color(0xFFF44336);
      case 'REJECTED':
        return const Color(0xFF9C27B0);
      default:
        return const Color(0xFF9E9E9E);
    }
  }

  static String labelFor(String status) {
    switch (status.toUpperCase()) {
      case 'CREATED':
        return 'En attente';
      case 'PLANNED':
        return 'Planifié';
      case 'RUNNING':
        return 'En cours';
      case 'REVIEW':
        return 'En révision';
      case 'DONE':
        return 'Terminé';
      case 'FAILED':
        return 'Échoué';
      case 'REJECTED':
        return 'Rejeté';
      default:
        return status;
    }
  }

  static IconData iconFor(String status) {
    switch (status.toUpperCase()) {
      case 'CREATED':
        return Icons.schedule;
      case 'PLANNED':
        return Icons.assignment;
      case 'RUNNING':
        return Icons.play_circle;
      case 'REVIEW':
        return Icons.visibility;
      case 'DONE':
        return Icons.check_circle;
      case 'FAILED':
        return Icons.error;
      case 'REJECTED':
        return Icons.block;
      default:
        return Icons.help_outline;
    }
  }
}
