import 'package:equatable/equatable.dart';
import 'package:json_annotation/json_annotation.dart';

part 'message.g.dart';

@JsonSerializable()
class Message extends Equatable {
  final String id;
  final String agentId;
  final String content;
  final MessageType type;
  final DateTime timestamp;
  final Map<String, dynamic> metadata;

  const Message({
    required this.id,
    required this.agentId,
    required this.content,
    required this.type,
    required this.timestamp,
    required this.metadata,
  });

  Message copyWith({
    String? id,
    String? agentId,
    String? content,
    MessageType? type,
    DateTime? timestamp,
    Map<String, dynamic>? metadata,
  }) {
    return Message(
      id: id ?? this.id,
      agentId: agentId ?? this.agentId,
      content: content ?? this.content,
      type: type ?? this.type,
      timestamp: timestamp ?? this.timestamp,
      metadata: metadata ?? this.metadata,
    );
  }

  @override
  List<Object> get props => [
    id,
    agentId,
    content,
    type,
    timestamp,
    metadata,
  ];

  factory Message.fromJson(Map<String, dynamic> json) => _$MessageFromJson(json);
  Map<String, dynamic> toJson() => _$MessageToJson(this);
}

enum MessageType {
  text,
  code,
  error,
  warning,
  info,
  system,
  toolCall,
  toolResponse,
}

@JsonSerializable()
class MessageUpdate extends Equatable {
  final String agentId;
  final String content;
  final MessageType type;
  final Map<String, dynamic> metadata;

  const MessageUpdate({
    required this.agentId,
    required this.content,
    required this.type,
    required this.metadata,
  });

  @override
  List<Object> get props => [
    agentId,
    content,
    type,
    metadata,
  ];

  factory MessageUpdate.fromJson(Map<String, dynamic> json) => _$MessageUpdateFromJson(json);
  Map<String, dynamic> toJson() => _$MessageUpdateToJson(this);
}