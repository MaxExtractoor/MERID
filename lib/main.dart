import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:merid/core/theme.dart';
import 'package:merid/home_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: MeridTheme.background,
      systemNavigationBarIconBrightness: Brightness.light,
    ),
  );
  
  runApp(const MeridApp());
}

class MeridApp extends StatelessWidget {
  const MeridApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MERID v2.0',
      debugShowCheckedModeBanner: false,
      theme: MeridTheme.darkTheme,
      home: const HomeScreen(),
    );
  }
}
