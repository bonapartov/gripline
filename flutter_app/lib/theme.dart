import 'package:flutter/material.dart';

const _primary = Color(0xFF1A1A2E);
const _accent = Color(0xFFE94560);
const _surface = Color(0xFF16213E);
const _onSurface = Color(0xFFEEEEEE);

final appTheme = ThemeData(
  useMaterial3: true,
  colorScheme: const ColorScheme.dark(
    primary: _accent,
    onPrimary: Colors.white,
    surface: _surface,
    onSurface: _onSurface,
    surfaceContainerHighest: Color(0xFF0F3460),
  ),
  scaffoldBackgroundColor: _primary,
  appBarTheme: const AppBarTheme(
    backgroundColor: _primary,
    foregroundColor: _onSurface,
    elevation: 0,
    centerTitle: false,
  ),
  navigationBarTheme: NavigationBarThemeData(
    backgroundColor: _surface,
    indicatorColor: _accent.withOpacity(0.2),
    iconTheme: WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.selected)) {
        return const IconThemeData(color: _accent);
      }
      return const IconThemeData(color: Colors.grey);
    }),
    labelTextStyle: WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.selected)) {
        return const TextStyle(color: _accent, fontSize: 12);
      }
      return const TextStyle(color: Colors.grey, fontSize: 12);
    }),
  ),
  cardTheme: CardTheme(
    color: _surface,
    elevation: 0,
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
  ),
  inputDecorationTheme: InputDecorationTheme(
    filled: true,
    fillColor: _surface,
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: BorderSide.none,
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: const BorderSide(color: _accent),
    ),
  ),
  elevatedButtonTheme: ElevatedButtonThemeData(
    style: ElevatedButton.styleFrom(
      backgroundColor: _accent,
      foregroundColor: Colors.white,
      minimumSize: const Size.fromHeight(50),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ),
  ),
);
