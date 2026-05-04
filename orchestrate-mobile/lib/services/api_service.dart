import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/agent.dart';
import '../models/workflow.dart';
import '../models/message.dart';
import 'logger_service.dart';

class ApiService {
  static ApiService? _instance;
  static ApiService get instance => _instance ??= ApiService._internal();
  
  ApiService._internal();
  
  final String _baseUrl = 'http://localhost:8000';
  final LoggerService _logger = LoggerService.instance;
  
  Future<List<Agent>> getAgents() async {
    try {
      final response = await http.get(Uri.parse('$_baseUrl/agents'));
      
      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(response.body);
        final agents = data.map((json) => Agent.fromJson(json)).toList();
        _logger.info('Retrieved ${agents.length} agents');
        return agents;
      } else {
        _logger.error('Failed to get agents: ${response.statusCode}');
        throw Exception('Failed to get agents');
      }
    } catch (e) {
      _logger.error('Error getting agents: $e');
      rethrow;
    }
  }
  
  Future<Agent> getAgent(String agentId) async {
    try {
      final response = await http.get(Uri.parse('$_baseUrl/agents/$agentId'));
      
      if (response.statusCode == 200) {
        final agent = Agent.fromJson(json.decode(response.body));
        _logger.info('Retrieved agent: ${agent.name}');
        return agent;
      } else {
        _logger.error('Failed to get agent: ${response.statusCode}');
        throw Exception('Failed to get agent');
      }
    } catch (e) {
      _logger.error('Error getting agent: $e');
      rethrow;
    }
  }
  
  Future<Agent> createAgent(String name, String type, String model, Map<String, dynamic> config) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/agents'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'name': name,
          'type': type,
          'model': model,
          'config': config,
        }),
      );
      
      if (response.statusCode == 201) {
        final agent = Agent.fromJson(json.decode(response.body));
        _logger.info('Created agent: ${agent.name}');
        return agent;
      } else {
        _logger.error('Failed to create agent: ${response.statusCode}');
        throw Exception('Failed to create agent');
      }
    } catch (e) {
      _logger.error('Error creating agent: $e');
      rethrow;
    }
  }
  
  Future<Agent> updateAgent(String agentId, String status, double progress, String message) async {
    try {
      final response = await http.put(
        Uri.parse('$_baseUrl/agents/$agentId'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'status': status,
          'progress': progress,
          'message': message,
        }),
      );
      
      if (response.statusCode == 200) {
        final agent = Agent.fromJson(json.decode(response.body));
        _logger.info('Updated agent: ${agent.name}');
        return agent;
      } else {
        _logger.error('Failed to update agent: ${response.statusCode}');
        throw Exception('Failed to update agent');
      }
    } catch (e) {
      _logger.error('Error updating agent: $e');
      rethrow;
    }
  }
  
  Future<void> deleteAgent(String agentId) async {
    try {
      final response = await http.delete(Uri.parse('$_baseUrl/agents/$agentId'));
      
      if (response.statusCode == 204) {
        _logger.info('Deleted agent: $agentId');
      } else {
        _logger.error('Failed to delete agent: ${response.statusCode}');
        throw Exception('Failed to delete agent');
      }
    } catch (e) {
      _logger.error('Error deleting agent: $e');
      rethrow;
    }
  }
  
  Future<List<Workflow>> getWorkflows() async {
    try {
      final response = await http.get(Uri.parse('$_baseUrl/workflows'));
      
      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(response.body);
        final workflows = data.map((json) => Workflow.fromJson(json)).toList();
        _logger.info('Retrieved ${workflows.length} workflows');
        return workflows;
      } else {
        _logger.error('Failed to get workflows: ${response.statusCode}');
        throw Exception('Failed to get workflows');
      }
    } catch (e) {
      _logger.error('Error getting workflows: $e');
      rethrow;
    }
  }
  
  Future<Workflow> getWorkflow(String workflowId) async {
    try {
      final response = await http.get(Uri.parse('$_baseUrl/workflows/$workflowId'));
      
      if (response.statusCode == 200) {
        final workflow = Workflow.fromJson(json.decode(response.body));
        _logger.info('Retrieved workflow: ${workflow.name}');
        return workflow;
      } else {
        _logger.error('Failed to get workflow: ${response.statusCode}');
        throw Exception('Failed to get workflow');
      }
    } catch (e) {
      _logger.error('Error getting workflow: $e');
      rethrow;
    }
  }
  
  Future<Workflow> createWorkflow(String name, String description, List<String> agentIds, String framework, Map<String, dynamic> config) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/workflows'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'name': name,
          'description': description,
          'agent_ids': agentIds,
          'framework': framework,
          'config': config,
        }),
      );
      
      if (response.statusCode == 201) {
        final workflow = Workflow.fromJson(json.decode(response.body));
        _logger.info('Created workflow: ${workflow.name}');
        return workflow;
      } else {
        _logger.error('Failed to create workflow: ${response.statusCode}');
        throw Exception('Failed to create workflow');
      }
    } catch (e) {
      _logger.error('Error creating workflow: $e');
      rethrow;
    }
  }
  
  Future<Workflow> updateWorkflow(String workflowId, String status, double progress, List<WorkflowStep> steps) async {
    try {
      final response = await http.put(
        Uri.parse('$_baseUrl/workflows/$workflowId'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'status': status,
          'progress': progress,
          'steps': steps.map((step) => step.toJson()).toList(),
        }),
      );
      
      if (response.statusCode == 200) {
        final workflow = Workflow.fromJson(json.decode(response.body));
        _logger.info('Updated workflow: ${workflow.name}');
        return workflow;
      } else {
        _logger.error('Failed to update workflow: ${response.statusCode}');
        throw Exception('Failed to update workflow');
      }
    } catch (e) {
      _logger.error('Error updating workflow: $e');
      rethrow;
    }
  }
  
  Future<void> deleteWorkflow(String workflowId) async {
    try {
      final response = await http.delete(Uri.parse('$_baseUrl/workflows/$workflowId'));
      
      if (response.statusCode == 204) {
        _logger.info('Deleted workflow: $workflowId');
      } else {
        _logger.error('Failed to delete workflow: ${response.statusCode}');
        throw Exception('Failed to delete workflow');
      }
    } catch (e) {
      _logger.error('Error deleting workflow: $e');
      rethrow;
    }
  }
  
  Future<void> startWorkflow(String workflowId) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/workflows/$workflowId/start'),
      );
      
      if (response.statusCode == 200) {
        _logger.info('Started workflow: $workflowId');
      } else {
        _logger.error('Failed to start workflow: ${response.statusCode}');
        throw Exception('Failed to start workflow');
      }
    } catch (e) {
      _logger.error('Error starting workflow: $e');
      rethrow;
    }
  }
  
  Future<void> stopWorkflow(String workflowId) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/workflows/$workflowId/stop'),
      );
      
      if (response.statusCode == 200) {
        _logger.info('Stopped workflow: $workflowId');
      } else {
        _logger.error('Failed to stop workflow: ${response.statusCode}');
        throw Exception('Failed to stop workflow');
      }
    } catch (e) {
      _logger.error('Error stopping workflow: $e');
      rethrow;
    }
  }
  
  Future<List<Message>> getMessages(String agentId, {int limit = 50}) async {
    try {
      final response = await http.get(
        Uri.parse('$_baseUrl/messages/$agentId?limit=$limit'),
      );
      
      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(response.body);
        final messages = data.map((json) => Message.fromJson(json)).toList();
        _logger.info('Retrieved ${messages.length} messages for agent: $agentId');
        return messages;
      } else {
        _logger.error('Failed to get messages: ${response.statusCode}');
        throw Exception('Failed to get messages');
      }
    } catch (e) {
      _logger.error('Error getting messages: $e');
      rethrow;
    }
  }
  
  Future<void> sendMessage(String agentId, String content, MessageType type) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/messages'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'agent_id': agentId,
          'content': content,
          'type': type.name,
        }),
      );
      
      if (response.statusCode == 201) {
        _logger.info('Sent message to agent: $agentId');
      } else {
        _logger.error('Failed to send message: ${response.statusCode}');
        throw Exception('Failed to send message');
      }
    } catch (e) {
      _logger.error('Error sending message: $e');
      rethrow;
    }
  }
  
  Future<Map<String, dynamic>> getSystemStatus() async {
    try {
      final response = await http.get(Uri.parse('$_baseUrl/status'));
      
      if (response.statusCode == 200) {
        final status = json.decode(response.body);
        _logger.info('Retrieved system status');
        return status;
      } else {
        _logger.error('Failed to get system status: ${response.statusCode}');
        throw Exception('Failed to get system status');
      }
    } catch (e) {
      _logger.error('Error getting system status: $e');
      rethrow;
    }
  }
}