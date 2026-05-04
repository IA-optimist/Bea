import 'package:equatable/equatable.dart';
import 'package:json_annotation/json_annotation.dart';

part 'agent.g.dart';

@JsonSerializable()
class Agent extends Equatable {
  final String id;
  final String name;
  final String type; // langchain, autogen, crewai, llamaindex, haystack, kimi
  final String status; // idle, running, completed, error
  final double progress;
  final String message;
  final String model;
  final Map<String, dynamic> config;
  final DateTime lastUpdate;
  final List<String> activeWorkflows;

  const Agent({
    required this.id,
    required this.name,
    required this.type,
    required this.status,
    required this.progress,
    required this.message,
    required this.model,
    required this.config,
    required this.lastUpdate,
    required this.activeWorkflows,
  });

  Agent copyWith({
    String? id,
    String? name,
    String? type,
    String? status,
    double? progress,
    String? message,
    String? model,
    Map<String, dynamic>? config,
    DateTime? lastUpdate,
    List<String>? activeWorkflows,
  }) {
    return Agent(
      id: id ?? this.id,
      name: name ?? this.name,
      type: type ?? this.type,
      status: status ?? this.status,
      progress: progress ?? this.progress,
      message: message ?? this.message,
      model: model ?? this.model,
      config: config ?? this.config,
      lastUpdate: lastUpdate ?? this.lastUpdate,
      activeWorkflows: activeWorkflows ?? this.activeWorkflows,
    );
  }

  static const empty = Agent(
    id: '',
    name: '',
    type: '',
    status: 'idle',
    progress: 0.0,
    message: '',
    model: '',
    config: {},
    lastUpdate: DateTime.now(),
    activeWorkflows: [],
  );

  @override
  List<Object> get props => [
    id,
    name,
    type,
    status,
    progress,
    message,
    model,
    config,
    lastUpdate,
    activeWorkflows,
  ];

  factory Agent.fromJson(Map<String, dynamic> json) => _$AgentFromJson(json);
  Map<String, dynamic> toJson() => _$AgentToJson(this);
}