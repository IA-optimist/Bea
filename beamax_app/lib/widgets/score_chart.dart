import '../theme/design_system.dart';
import 'dart:math';
import 'package:flutter/material.dart';

/// Graphique en ligne des derniers scores advisory.
/// Utilise uniquement CustomPainter — zéro dépendance externe.
class ScoreChart extends StatelessWidget {
  final List<double> scores;

  const ScoreChart({super.key, required this.scores});

  @override
  Widget build(BuildContext context) {
    if (scores.isEmpty) {
      return const SizedBox(
        height: 120,
        child: Center(
          child: Text(
            'Aucune donnée de score',
            style: TextStyle(color: JvColors.textMut, fontSize: 12),
          ),
        ),
      );
    }

    return Container(
      height: 140,
      padding: const EdgeInsets.only(top: 8, bottom: 4, left: 4, right: 4),
      child: CustomPaint(
        painter: _ScoreChartPainter(scores: scores),
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _ScoreChartPainter extends CustomPainter {
  final List<double> scores;

  _ScoreChartPainter({required this.scores});

  static const double _paddingLeft = 28;
  static const double _paddingRight = 8;
  static const double _paddingTop = 8;
  static const double _paddingBottom = 20;

  @override
  void paint(Canvas canvas, Size size) {
    final drawWidth  = size.width  - _paddingLeft - _paddingRight;
    final drawHeight = size.height - _paddingTop  - _paddingBottom;

    // Normalise : max 10 scores
    final pts = scores.length > 10 ? scores.sublist(scores.length - 10) : scores;
    final n = pts.length;

    double xFor(int i) => _paddingLeft + (n == 1 ? drawWidth / 2 : i * drawWidth / (n - 1));
    double yFor(double v) => _paddingTop + drawHeight - (v.clamp(0.0, 10.0) / 10.0) * drawHeight;

    // ── Axe Y labels ─────────────────────────────────────────────────────────
    final axisPaint = Paint()
      ..color = JvColors.border
      ..strokeWidth = 0.8
      ..style = PaintingStyle.stroke;

    for (final v in [0.0, 2.5, 5.0, 7.5, 10.0]) {
      final y = yFor(v);
      canvas.drawLine(Offset(_paddingLeft, y), Offset(size.width - _paddingRight, y), axisPaint);
      final tp = TextPainter(
        text: TextSpan(
          text: v.toStringAsFixed(0),
          style: const TextStyle(color: JvColors.textMut, fontSize: 8),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(0, y - 5));
    }

    // ── Ligne seuil GO 7.5 (vert pointillé) ──────────────────────────────────
    _drawDashedLine(
      canvas,
      Offset(_paddingLeft, yFor(7.5)),
      Offset(size.width - _paddingRight, yFor(7.5)),
      const Color(0xFF00E676),
      dash: 6,
      gap: 4,
      strokeWidth: 1.2,
    );

    // ── Ligne seuil IMPROVE 4.0 (orange pointillé) ───────────────────────────
    _drawDashedLine(
      canvas,
      Offset(_paddingLeft, yFor(4.0)),
      Offset(size.width - _paddingRight, yFor(4.0)),
      const Color(0xFFFF9100),
      dash: 5,
      gap: 4,
      strokeWidth: 1.0,
    );

    if (n == 0) return;

    // ── Construire les points de la courbe ────────────────────────────────────
    final offsets = List.generate(n, (i) => Offset(xFor(i), yFor(pts[i])));

    // ── Zone colorée sous la courbe (fill) ────────────────────────────────────
    final fillPath = Path()..moveTo(offsets.first.dx, _paddingTop + drawHeight);
    for (final o in offsets) {
      fillPath.lineTo(o.dx, o.dy);
    }
    fillPath
      ..lineTo(offsets.last.dx, _paddingTop + drawHeight)
      ..close();

    final fillPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          const Color(0xFF00E5FF).withValues(alpha:0.25),
          const Color(0xFF00E5FF).withValues(alpha:0.02),
        ],
      ).createShader(Rect.fromLTWH(0, _paddingTop, size.width, drawHeight))
      ..style = PaintingStyle.fill;

    canvas.drawPath(fillPath, fillPaint);

    // ── Ligne cyan ────────────────────────────────────────────────────────────
    final linePath = Path()..moveTo(offsets.first.dx, offsets.first.dy);
    for (int i = 1; i < offsets.length; i++) {
      linePath.lineTo(offsets[i].dx, offsets[i].dy);
    }

    final linePaint = Paint()
      ..color = JvColors.cyan
      ..strokeWidth = 2.0
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    canvas.drawPath(linePath, linePaint);

    // ── Points ────────────────────────────────────────────────────────────────
    final dotPaint = Paint()
      ..color = JvColors.cyan
      ..style = PaintingStyle.fill;
    final dotBorder = Paint()
      ..color = JvColors.card
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;

    for (int i = 0; i < offsets.length; i++) {
      final o = offsets[i];
      canvas.drawCircle(o, 4, dotPaint);
      canvas.drawCircle(o, 4, dotBorder);

      // Label score sur chaque point
      final tp = TextPainter(
        text: TextSpan(
          text: pts[i].toStringAsFixed(1),
          style: const TextStyle(color: JvColors.textSec, fontSize: 7),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(o.dx - tp.width / 2, o.dy - 14));
    }

    // ── Axe X : index des missions ────────────────────────────────────────────
    for (int i = 0; i < n; i++) {
      final tp = TextPainter(
        text: TextSpan(
          text: 'M${i + 1}',
          style: const TextStyle(color: JvColors.textMut, fontSize: 8),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(xFor(i) - tp.width / 2, size.height - _paddingBottom + 4));
    }
  }

  void _drawDashedLine(
    Canvas canvas,
    Offset start,
    Offset end,
    Color color, {
    double dash = 6,
    double gap = 4,
    double strokeWidth = 1,
  }) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = strokeWidth
      ..style = PaintingStyle.stroke;

    final total = (end - start).distance;
    final dir = (end - start) / total;
    double drawn = 0;

    while (drawn < total) {
      final segEnd = min(drawn + dash, total);
      canvas.drawLine(start + dir * drawn, start + dir * segEnd, paint);
      drawn = segEnd + gap;
    }
  }

  @override
  bool shouldRepaint(_ScoreChartPainter old) => old.scores != scores;
}
