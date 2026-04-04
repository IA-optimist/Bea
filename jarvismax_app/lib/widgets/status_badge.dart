import 'package:flutter/material.dart';

class StatusBadge extends StatelessWidget {
  final String label;
  final Color color;
  final double fontSize;

  const StatusBadge({
    super.key,
    required this.label,
    required this.color,
    this.fontSize = 10,
  });

  factory StatusBadge.forStatus(String status, {double fontSize = 10}) {
    final color = switch (status) {
      'PENDING' || 'PENDING_VALIDATION' => JvColors.orange,
      'APPROVED' || 'EXECUTING'         => JvColors.cyan,
      'DONE' || 'EXECUTED'              => JvColors.green,
      'REJECTED' || 'BLOCKED' || 'FAILED' => JvColors.red,
      'ANALYZING'                       => JvColors.cyanDark,
      _                                 => JvColors.textMut,
    };
    return StatusBadge(label: status.replaceAll('_', ' '), color: color, fontSize: fontSize);
  }

  factory StatusBadge.forRisk(String risk, {double fontSize = 10}) {
    final color = switch (risk) {
      'LOW'      => JvColors.green,
      'MEDIUM'   => JvColors.orange,
      'HIGH'     => JvColors.red,
      'CRITICAL' => const Color(0xFFAA00FF),
      _          => JvColors.textMut,
    };
    return StatusBadge(label: risk, color: color, fontSize: fontSize);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha:0.15),
        border: Border.all(color: color.withValues(alpha:0.5)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: fontSize,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}
