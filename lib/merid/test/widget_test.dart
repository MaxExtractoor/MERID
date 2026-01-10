// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';

import 'package:merid/main.dart';

void main() {
  testWidgets('MERID app loads correctly', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const MeridApp());

    // Verify that the app title is present.
    expect(find.text('MERID v2.0 // LOCAL'), findsOneWidget);
    
    // Verify that the distillation gate is present.
    expect(find.text('DISTILLED OUTPUT'), findsOneWidget);
    
    // Verify that the default system message is displayed.
    expect(find.text('SYSTEM NOMINAL // WAITING FOR INPUT'), findsOneWidget);
  });
}
