import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';

class RealtimeService {
  final WebSocketChannel channel =
      WebSocketChannel.connect(Uri.parse('ws://localhost:8080'));

  Stream<dynamic> get stream =>
      channel.stream.map((event) => jsonDecode(event));

  void dispose() {
    channel.sink.close();
  }
}
