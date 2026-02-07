import 'package:flutter/material.dart';

class MeridTheme {
  static const Color background = Color(0xFF020617);
  static const Color surface = Color(0xFF0f172a);
  static const Color surfaceLight = Color(0xFF1e293b);

  static const Color amber = Color(0xFFf59e0b);
  static const Color emerald = Color(0xFF10b981);
  static const Color rose = Color(0xFFf43f5e);

  static const Color textPrimary = Color(0xFFf1f5f9);
  static const Color textSecondary = Color(0xFF94a3b8);
  static const Color textDim = Color(0xFF64748b);

  static const String fontFamily = 'JetBrainsMono';

  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: background,
      primaryColor: amber,
      colorScheme: const ColorScheme.dark(
        primary: amber,
        secondary: emerald,
        error: rose,
        surface: surface,
      ),
      fontFamily: fontFamily,
      textTheme: const TextTheme(
        displayLarge: TextStyle(
            fontSize: 32, fontWeight: FontWeight.bold, color: textPrimary),
        displayMedium: TextStyle(
            fontSize: 24, fontWeight: FontWeight.bold, color: textPrimary),
        displaySmall: TextStyle(
            fontSize: 20, fontWeight: FontWeight.bold, color: textPrimary),
        bodyLarge: TextStyle(fontSize: 16, color: textPrimary),
        bodyMedium: TextStyle(fontSize: 14, color: textSecondary),
        bodySmall: TextStyle(fontSize: 12, color: textDim),
        labelLarge: TextStyle(
            fontSize: 14, fontWeight: FontWeight.w600, color: textPrimary),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: background,
        elevation: 0,
        iconTheme: IconThemeData(color: textPrimary),
        titleTextStyle: TextStyle(
          color: textPrimary,
          fontSize: 18,
          fontWeight: FontWeight.bold,
          fontFamily: fontFamily,
        ),
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: const BorderSide(color: surfaceLight, width: 1),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: amber,
          foregroundColor: background,
          textStyle: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.bold,
            fontFamily: fontFamily,
          ),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: amber,
          side: const BorderSide(color: amber, width: 1),
          textStyle: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.bold,
            fontFamily: fontFamily,
          ),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
        ),
      ),
    );
  }

  static BoxDecoration glowBox({
    Color color = amber,
    double intensity = 0.3,
  }) {
    return BoxDecoration(
      color: surface,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: color.withValues(alpha: 0.5), width: 1),
      boxShadow: [
        BoxShadow(
          color: color.withValues(alpha: intensity),
          blurRadius: 12,
          spreadRadius: 0,
        ),
      ],
    );
  }

  static TextStyle monoStyle({
    double fontSize = 14,
    Color color = textPrimary,
    FontWeight weight = FontWeight.normal,
  }) {
    return TextStyle(
      fontFamily: fontFamily,
      fontSize: fontSize,
      color: color,
      fontWeight: weight,
      letterSpacing: -0.5,
    );
  }
}
