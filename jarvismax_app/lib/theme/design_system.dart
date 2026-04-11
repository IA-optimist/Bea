import 'dart:math' as math;
import 'package:flutter/material.dart';

// ═══════════════════════════════════════════════════════════════════════════════
// JARVIS DESIGN SYSTEM v3
// Premium, calm, high-trust. Matches web app.html design tokens.
// ═══════════════════════════════════════════════════════════════════════════════

// ── Legacy JvColors compat — maps old cyan-themed palette to JDS tokens ─────
// Used by: mission_screen.dart, actions_screen.dart, and their sub-widgets.
// TODO: Migrate all JvColors references to JDS directly.
class JvColors {
  JvColors._();
  static const bg       = JDS.bgBase;
  static const surface  = JDS.bgSurface;
  static const card     = JDS.bgElevated;
  static const border   = JDS.borderDefault;
  static const cyan     = JDS.blue;     // Primary accent: cyan → blue
  static const cyanDark = Color(0xFF2563EB); // Darker blue
  static const green    = JDS.green;
  static const orange   = JDS.amber;
  static const red      = JDS.red;
  static const textPrim = JDS.textPrimary;
  static const textSec  = JDS.textSecondary;
  static const textMut  = JDS.textMuted;
  static const text     = JDS.textPrimary;
  static const error    = JDS.red;
  static const success  = JDS.green;
  static const warning  = JDS.amber;
}

// ── Tokens ───────────────────────────────────────────────────────────────────

class JDS {
  JDS._();

  // ── Surface ──
  static const bgBase     = Color(0xFF09090B);
  static const bgSurface  = Color(0xFF111113);
  static const bgElevated = Color(0xFF18181B);
  static const bgOverlay  = Color(0xFF1F1F23);
  static const bgHover    = Color(0xFF27272A);
  static const bgActive   = Color(0xFF2D2D32);

  // ── Border ──
  static const borderSubtle  = Color(0xFF1F1F23);
  static const borderDefault = Color(0xFF27272A);
  static const borderStrong  = Color(0xFF3F3F46);
  static const borderFocus   = Color(0xFF3B82F6);

  // ── Text ──
  static const textPrimary   = Color(0xFFFAFAFA);
  static const textSecondary = Color(0xFFA1A1AA);
  static const textMuted     = Color(0xFF71717A);
  static const textDim       = Color(0xFF52525B);

  // ── Accent ──
  static const blue      = Color(0xFF3B82F6);
  static const blueSoft  = Color(0x1A3B82F6); // 10%
  static const blueGlow  = Color(0x333B82F6); // 20%
  static const green     = Color(0xFF22C55E);
  static const greenSoft = Color(0x1A22C55E);
  static const amber     = Color(0xFFF59E0B);
  static const amberSoft = Color(0x1AF59E0B);
  static const red       = Color(0xFFEF4444);
  static const redSoft   = Color(0x1AEF4444);
  static const violet    = Color(0xFF8B5CF6);
  static const violetSoft= Color(0x1A8B5CF6);

  // ── Radius ──
  static const double radiusSm = 6;
  static const double radiusMd = 10;
  static const double radiusLg = 14;
  static const double radiusXl = 20;

  // ── Spacing ──
  static const double space4  = 4;
  static const double space8  = 8;
  static const double space12 = 12;
  static const double space16 = 16;
  static const double space20 = 20;
  static const double space24 = 24;
  static const double space32 = 32;
  static const double space48 = 48;

  // ── Status Colors ──
  static Color statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'running': case 'active': case 'executing':
        return blue;
      case 'completed': case 'done': case 'success': case 'ready':
        return green;
      case 'failed': case 'error': case 'critical':
        return red;
      case 'pending': case 'awaiting_approval': case 'warning': case 'degraded':
        return amber;
      case 'blocked': case 'disabled':
        return textDim;
      default:
        return textMuted;
    }
  }

  static Color riskColor(String risk) {
    switch (risk.toLowerCase()) {
      case 'critical': return red;
      case 'high': return red;
      case 'medium': return amber;
      case 'low': return green;
      default: return textMuted;
    }
  }
}

// ── Theme ────────────────────────────────────────────────────────────────────

class JarvisTheme {
  JarvisTheme._();

  static ThemeData get dark => ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: JDS.bgBase,
    fontFamily: '.SF Pro Text',
    colorScheme: const ColorScheme.dark(
      primary:   JDS.blue,
      secondary: JDS.violet,
      surface:   JDS.bgSurface,
      error:     JDS.red,
      onPrimary: Colors.white,
      onSurface: JDS.textPrimary,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: JDS.bgBase,
      foregroundColor: JDS.textPrimary,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.w700,
        color: JDS.textPrimary,
        letterSpacing: -0.3,
      ),
    ),
    bottomNavigationBarTheme: const BottomNavigationBarThemeData(
      backgroundColor: JDS.bgSurface,
      selectedItemColor: JDS.blue,
      unselectedItemColor: JDS.textMuted,
      selectedLabelStyle: TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
      unselectedLabelStyle: TextStyle(fontSize: 11),
      elevation: 0,
      type: BottomNavigationBarType.fixed,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: JDS.bgElevated,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        borderSide: const BorderSide(color: JDS.borderDefault),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        borderSide: const BorderSide(color: JDS.borderDefault),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        borderSide: const BorderSide(color: JDS.borderFocus, width: 1.5),
      ),
      hintStyle: const TextStyle(color: JDS.textDim, fontSize: 15),
      labelStyle: const TextStyle(color: JDS.textSecondary),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: JDS.blue,
        foregroundColor: Colors.white,
        elevation: 0,
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(JDS.radiusMd)),
        textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: JDS.blue,
        side: const BorderSide(color: JDS.borderDefault),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(JDS.radiusMd)),
      ),
    ),
    textTheme: const TextTheme(
      headlineLarge: TextStyle(color: JDS.textPrimary, fontSize: 28, fontWeight: FontWeight.w700, letterSpacing: -0.5),
      headlineMedium: TextStyle(color: JDS.textPrimary, fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: -0.3),
      titleLarge: TextStyle(color: JDS.textPrimary, fontSize: 17, fontWeight: FontWeight.w600),
      titleMedium: TextStyle(color: JDS.textPrimary, fontSize: 15, fontWeight: FontWeight.w600),
      bodyLarge: TextStyle(color: JDS.textPrimary, fontSize: 15, height: 1.5),
      bodyMedium: TextStyle(color: JDS.textSecondary, fontSize: 14, height: 1.5),
      bodySmall: TextStyle(color: JDS.textMuted, fontSize: 12),
      labelLarge: TextStyle(color: JDS.blue, fontSize: 13, fontWeight: FontWeight.w600),
    ),
    dividerTheme: const DividerThemeData(color: JDS.borderSubtle, thickness: 1, space: 1),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: JDS.bgElevated,
      contentTextStyle: const TextStyle(color: JDS.textPrimary, fontSize: 14),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(JDS.radiusSm)),
      behavior: SnackBarBehavior.floating,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: JDS.bgElevated,
      labelStyle: const TextStyle(color: JDS.textPrimary, fontSize: 13),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(JDS.radiusXl),
        side: const BorderSide(color: JDS.borderDefault),
      ),
      side: const BorderSide(color: JDS.borderDefault),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: JDS.blue),
    cardTheme: CardThemeData(
      color: JDS.bgSurface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        side: const BorderSide(color: JDS.borderSubtle),
      ),
      margin: EdgeInsets.zero,
    ),
  );
}

// ── Reusable Widgets ─────────────────────────────────────────────────────────

/// Status badge (pill shape, colored background).
class JStatusBadge extends StatelessWidget {
  final String label;
  final Color color;
  const JStatusBadge({super.key, required this.label, required this.color});

  factory JStatusBadge.fromStatus(String status) {
    return JStatusBadge(
      label: status.replaceAll('_', ' ').toUpperCase(),
      color: JDS.statusColor(status),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(JDS.radiusXl),
      ),
      child: Text(label, style: TextStyle(
        fontSize: 10, fontWeight: FontWeight.w700,
        color: color, letterSpacing: 0.5,
      )),
    );
  }
}

/// Risk badge.
class JRiskBadge extends StatelessWidget {
  final String risk;
  const JRiskBadge({super.key, required this.risk});

  @override
  Widget build(BuildContext context) {
    final color = JDS.riskColor(risk);
    final label = switch (risk.toLowerCase()) {
      'critical' => 'Critical risk',
      'high' => 'High risk',
      'medium' => 'Medium risk',
      'low' => 'Low risk',
      _ => risk,
    };
    final icon = switch (risk.toLowerCase()) {
      'critical' || 'high' => Icons.warning_rounded,
      'medium' => Icons.info_rounded,
      _ => Icons.shield_rounded,
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(JDS.radiusXl),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 12, color: color),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(
          fontSize: 11, fontWeight: FontWeight.w600, color: color,
        )),
      ]),
    );
  }
}

/// Status dot (small colored circle).
class JStatusDot extends StatelessWidget {
  final String status;
  final double size;
  const JStatusDot({super.key, required this.status, this.size = 8});

  @override
  Widget build(BuildContext context) {
    final color = JDS.statusColor(status);
    return Container(
      width: size, height: size,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        boxShadow: status.toLowerCase() == 'running'
            ? [BoxShadow(color: color.withValues(alpha: 0.4), blurRadius: 6)]
            : null,
      ),
    );
  }
}

/// Elevated card with optional border color.
class JCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final Color? borderColor;
  final VoidCallback? onTap;

  const JCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.borderColor,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: padding,
        decoration: BoxDecoration(
          color: JDS.bgSurface,
          borderRadius: BorderRadius.circular(JDS.radiusMd),
          border: Border.all(color: borderColor ?? JDS.borderSubtle),
        ),
        child: child,
      ),
    );
  }
}

/// Loading skeleton placeholder.
class JSkeleton extends StatefulWidget {
  final double width;
  final double height;
  final double borderRadius;

  const JSkeleton({
    super.key,
    this.width = double.infinity,
    required this.height,
    this.borderRadius = 6,
  });

  @override
  State<JSkeleton> createState() => _JSkeletonState();
}

class _JSkeletonState extends State<JSkeleton>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return JAnimatedBuilder(
      listenable: _controller,
      builder: (_, __) {
        final opacity = 0.08 + 0.06 * (0.5 + 0.5 * math.cos(_controller.value * 2 * math.pi));
        return Container(
          width: widget.width,
          height: widget.height,
          decoration: BoxDecoration(
            color: JDS.textPrimary.withValues(alpha: opacity),
            borderRadius: BorderRadius.circular(widget.borderRadius),
          ),
        );
      },
    );
  }
}

/// Animated builder helper for skeleton.
class JAnimatedBuilder extends AnimatedWidget {
  final Widget Function(BuildContext, Widget?) builder;
  const JAnimatedBuilder({super.key, required super.listenable, required this.builder});

  @override
  Widget build(BuildContext context) => builder(context, null);

  Animation<double> get animation => listenable as Animation<double>;
}

/// Empty state widget.
class JEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Widget? action;

  const JEmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle = '',
    this.action,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 48, color: JDS.textDim),
          const SizedBox(height: 16),
          Text(title, style: const TextStyle(
            fontSize: 16, fontWeight: FontWeight.w600, color: JDS.textSecondary,
          ), textAlign: TextAlign.center),
          if (subtitle.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(subtitle, style: const TextStyle(
              fontSize: 13, color: JDS.textMuted,
            ), textAlign: TextAlign.center),
          ],
          if (action != null) ...[
            const SizedBox(height: 20),
            action!,
          ],
        ]),
      ),
    );
  }
}

/// Section header with optional action.
class JSectionHeader extends StatelessWidget {
  final String title;
  final String? count;
  final Widget? action;

  const JSectionHeader({
    super.key,
    required this.title,
    this.count,
    this.action,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(children: [
        Text(title.toUpperCase(), style: const TextStyle(
          fontSize: 11, fontWeight: FontWeight.w600,
          color: JDS.textMuted, letterSpacing: 0.8,
        )),
        if (count != null) ...[
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
            decoration: BoxDecoration(
              color: JDS.bgOverlay,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(count!, style: const TextStyle(
              fontSize: 10, color: JDS.textDim, fontWeight: FontWeight.w600,
            )),
          ),
        ],
        const Spacer(),
        if (action != null) action!,
      ]),
    );
  }
}

/// Readiness meter (horizontal progress bar).
class JReadinessMeter extends StatelessWidget {
  final double value; // 0.0 - 1.0
  final String? label;

  const JReadinessMeter({super.key, required this.value, this.label});

  @override
  Widget build(BuildContext context) {
    final pct = (value * 100).round();
    final color = pct >= 70 ? JDS.green : pct >= 40 ? JDS.amber : JDS.red;

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (label != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(children: [
            Text(label!, style: const TextStyle(
              fontSize: 12, color: JDS.textSecondary, fontWeight: FontWeight.w500,
            )),
            const Spacer(),
            Text('$pct%', style: TextStyle(
              fontSize: 12, color: color, fontWeight: FontWeight.w700,
            )),
          ]),
        ),
      Container(
        height: 6,
        decoration: BoxDecoration(
          color: JDS.bgOverlay,
          borderRadius: BorderRadius.circular(3),
        ),
        child: FractionallySizedBox(
          alignment: Alignment.centerLeft,
          widthFactor: value.clamp(0.0, 1.0),
          child: Container(
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(3),
            ),
          ),
        ),
      ),
    ]);
  }
}
