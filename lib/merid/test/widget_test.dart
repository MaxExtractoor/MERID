// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

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

  testWidgets('ControlStation fetches and toggles lockdown', (WidgetTester tester) async {
    // Mock responses for GET and POST
    final client = MockClient((request) async {
      if (request.method == 'GET' && request.url.path == '/admin/lockdown') {
        return http.Response('{"lockdown": false}', 200);
      }
      if (request.method == 'POST' && request.url.path == '/admin/lockdown') {
        // Accept any post
        return http.Response('', 204);
      }
      return http.Response('Not Found', 404);
    });

    await tester.pumpWidget(MaterialApp(home: ControlStation(httpClient: client)));

    // initial fetch happens in initState; allow it to process
    await tester.pumpAndSettle();

    // Floating button should show LOCKDOWN when not locked
    expect(find.text('LOCKDOWN'), findsOneWidget);

    // Tap the button, a token dialog appears; submit token
    await tester.tap(find.byType(FloatingActionButton));
    await tester.pumpAndSettle();

    // Enter token and submit
    await tester.enterText(find.byType(TextField).first, 't1');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    // After submitting token and mock POST returning 204, the button text should become UNLOCK
    await tester.pumpAndSettle();
    expect(find.text('UNLOCK'), findsOneWidget);
  });
}
