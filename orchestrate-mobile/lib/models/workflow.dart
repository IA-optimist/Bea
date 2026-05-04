import 'package:equatable/equatable.dart';
import 'package:json_annotation/json_annotation.dart';

part 'workflow.g.dart';

@JsonSerializable()
class Workflow extends Equatable {
  final String id;
  final String name;
  final String description;
  final List<String> agentIds;
  final String status; // pending, running, completed, error
  final double progress;
  final List<WorkflowStep> steps;
  final DateTime startTime;
  final DateTime? endTime;
  final Map<String, dynamic> config;
  final String framework; // langchain, autogen, crewai, llamaindex, haystack, kimi

  const Workflow({
    required this.id,
    required this.name,
    required this.description,
    required this.agentIds,
    required this.status,
    required this.progress,
    required this.steps,
    required this.startTime,
    this.endTime,
    required this.config,
    required this.framework,
  });

  Workflow copyWith({
    String? id,
    String? name,
    String? description,
    List<String>? agentIds,
    String? status,
    double? progress,
    List<WorkflowStep>? steps,
    DateTime? startTime,
    DateTime? endTime,
    Map<String, dynamic>? config,
    String? framework,
  }) {
    return Workflow(
      id: id ?? this.id,
      name: name ?? this.name,
      description: description ?? this.description,
      agentIds: agentIds ?? this.agentIds,
      status: status ?? this.status,
      progress: progress ?? this.progress,
      steps: steps ?? this.steps,
      startTime: startTime ?? this.startTime,
      endTime: endTime ?? this.endTime,
      config: config ?? this.config,
      framework: framework ?? this.framework,
    );
  }

  static const empty = Workflow(
    id: '',
    name: '',
    description: '',
    agentIds: [],
    status: 'pending',
    progress: 0.0,
    steps: [],
    startTime: DateTime.now(),
    config: {},
    framework: '',
  );

  @override
  List<Object> get props => [
    id,
    name,
    description,
    agentIds,
    status,
    progress,
    steps,
    startTime,
    endTime,
    config,
    framework,
  ];

  factory Workflow.fromJson(Map<String, dynamic> json) => _$WorkflowFromJson(json);
  Map<String, dynamic> toJson() => _$WorkflowToJson(this);
}

@JsonSerializable()
class WorkflowStep extends Equatable {
  final String id;
  final String name;
  final String agentId;
  final String status; // pending, running, completed, error
  final double progress;
  final String message;
  final DateTime startTime;
  final DateTime? endTime;

  const WorkflowStep({
    required this.id,
    required this.name,
    required this.agentId,
    required this.status,
    required this.progress,
    required this.message,
    required this.startTime,
    this.endTime,
  });

  WorkflowStep copyWith({
    String? id,
    String? name,
    String? agentId,
    String? status,
    double? progress,
    String? message,
    DateTime? startTime,
    DateTime? endTime,
  }) {
    return WorkflowStep(
      id: id ?? this.id,
      name: name ?? this.name,
      agentId: agentId ?? this.agentId,
      status: status ?? this.status,
      progress: progress ?? this.progress,
      message: message ?? this.message,
      startTime: startTime ?? this.startTime,
      endTime: endTime ?? this.endTime,
    );
  }

  @override
  List<Object> get props => [
    id,
    name,
    agentId,
    status,
    progress,
    message,
    startTime,
    endTime,
  ];

  factory WorkflowStep.fromJson(Map<String, dynamic> json) => _$WorkflowStepFromJson(json);
  Map<String, dynamic> toJson() => _$WorkflowStepToJson(this);
}