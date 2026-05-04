import 'dart:io';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/io.dart';
import 'dart:convert';
import '../models/agent.dart';
import '../models/workflow.dart';
import '../models/message.dart';
import 'logger_service.dart';

class WebSocketService {
  static WebSocketService? _instance;
  static WebSocketService get instance => _instance ??= WebSocketService._internal();
  
  WebSocketService._internal();
  
  WebSocketChannel? _channel;
  bool get isConnected => _channel?.closeCode == null;
  
  final Map<String, Function(Agent)> _agentListeners = {};
  final Map<String, Function(Workflow)> _workflowListeners = {};
  final List<Function(Message)> _messageListeners = [];
  final List<Function(MessageUpdate)> _messageUpdateListeners = [];
  final List<Function()> _connectionListeners = [];
  
  final LoggerService _logger = LoggerService.instance;
  
  Future<void> connect(String url) async {
    try {
      _channel = IOWebSocketChannel.connect(url);
      _logger.info('WebSocket connected to $url');
      
      _channel?.stream.listen(
        (data) {
          _handleMessage(data);
        },
        onError: (error) {
          _logger.error('WebSocket error: $error');
          _notifyConnectionListeners();
        },
        onDone: () {
          _logger.info('WebSocket disconnected');
          _notifyConnectionListeners();
        },
      );
      
      _notifyConnectionListeners();
    } catch (e) {
      _logger.error('Failed to connect to WebSocket: $e');
      rethrow;
    }
  }
  
  void disconnect() {
    _channel?.sink.close();
    _channel = null;
    _logger.info('WebSocket disconnected');
    _notifyConnectionListeners();
  }
  
  void _handleMessage(String data) {
    try {
      final message = json.decode(data);
      final type = message['type'];
      
      switch (type) {
        case 'agent_update':
          _handleAgentUpdate(message);
          break;
        case 'workflow_update':
          _handleWorkflowUpdate(message);
          break;
        case 'message':
          _handleMessageEvent(message);
          break;
        case 'message_update':
          _handleMessageUpdate(message);
          break;
        case '3d_update':
          _handle3DUpdate(message);
          break;
        default:
          _logger.warning('Unknown message type: $type');
      }
    } catch (e) {
      _logger.error('Error handling WebSocket message: $e');
    }
  }
  
  void _handleAgentUpdate(Map<String, dynamic> message) {
    final agent = Agent.fromJson(message['data']);
    _logger.info('Agent update: ${agent.name} (${agent.status})');
    
    for (final listener in _agentListeners.values) {
      listener(agent);
    }
  }
  
  void _handleWorkflowUpdate(Map<String, dynamic> message) {
    final workflow = Workflow.fromJson(message['data']);
    _logger.info('Workflow update: ${workflow.name} (${workflow.status})');
    
    for (final listener in _workflowListeners.values) {
      listener(workflow);
    }
  }
  
  void _handleMessageEvent(Map<String, dynamic> message) {
    final msg = Message.fromJson(message['data']);
    _logger.info('Message from ${msg.agentId}: ${msg.content}');
    
    for (final listener in _messageListeners) {
      listener(msg);
    }
  }
  
  void _handleMessageUpdate(Map<String, dynamic> message) {
    final update = MessageUpdate.fromJson(message['data']);
    _logger.info('Message update from ${update.agentId}: ${update.content}');
    
    for (final listener in _messageUpdateListeners) {
      listener(update);
    }
  }
  
  void _handle3DUpdate(Map<String, dynamic> message) {
    final data = message['data'];
    _logger.info('3D update received');
    
    // Gérer les mises à jour 3D
    // Peut être utilisé pour mettre à jour le dashboard 3D
  }
  
  void subscribeToAgent(String agentId, Function(Agent) listener) {
    _agentListeners[agentId] = listener;
  }
  
  void unsubscribeFromAgent(String agentId) {
    _agentListeners.remove(agentId);
  }
  
  void subscribeToWorkflow(String workflowId, Function(Workflow) listener) {
    _workflowListeners[workflowId] = listener;
  }
  
  void unsubscribeFromWorkflow(String workflowId) {
    _workflowListeners.remove(workflowId);
  }
  
  void subscribeToMessages(Function(Message) listener) {
    _messageListeners.add(listener);
  }
  
  void unsubscribeFromMessages(Function(Message) listener) {
    _messageListeners.remove(listener);
  }
  
  void subscribeToMessageUpdates(Function(MessageUpdate) listener) {
    _messageUpdateListeners.add(listener);
  }
  
  void unsubscribeFromMessageUpdates(Function(MessageUpdate) listener) {
    _messageUpdateListeners.remove(listener);
  }
  
  void subscribeToConnection(Function() listener) {
    _connectionListeners.add(listener);
  }
  
  void unsubscribeFromConnection(Function() listener) {
    _connectionListeners.remove(listener);
  }
  
  void _notifyConnectionListeners() {
    for (final listener in _connectionListeners) {
      listener();
    }
  }
  
  void sendAgentCommand(String agentId, String command, Map<String, dynamic> params) {
    if (!isConnected) {
      _logger.error('WebSocket not connected');
      return;
    }
    
    final message = {
      'type': 'agent_command',
      'agent_id': agentId,
      'command': command,
      'params': params,
      'timestamp': DateTime.now().toIso8601String(),
    };
    
    _channel?.sink.add(json.encode(message));
    _logger.info('Sent command to $agentId: $command');
  }
  
  void startWorkflow(String workflowId, String name, List<String> agentIds, String framework) {
    if (!isConnected) {
      _logger.error('WebSocket not connected');
      return;
    }
    
    final message = {
      'type': 'start_workflow',
      'workflow_id': workflowId,
      'name': name,
      'agent_ids': agentIds,
      'framework': framework,
      'timestamp': DateTime.now().toIso8601String(),
    };
    
    _channel?.sink.add(json.encode(message));
    _logger.info('Started workflow: $name');
  }
  
  void stopWorkflow(String workflowId) {
    if (!isConnected) {
      _logger.error('WebSocket not connected');
      return;
    }
    
    final message = {
      'type': 'stop_workflow',
      'workflow_id': workflowId,
      'timestamp': DateTime.now().toIso8601String(),
    };
    
    _channel?.sink.add(json.encode(message));
    _logger.info('Stopped workflow: $workflowId');
  }
  
  void sendPrompt(String agentId, String prompt, Map<String, dynamic> config) {
    if (!isConnected) {
      _logger.error('WebSocket not connected');
      return;
    }
    
    final message = {
      'type': 'prompt',
      'agent_id': agentId,
      'prompt': prompt,
      'config': config,
      'timestamp': DateTime.now().toIso8601String(),
    };
    
    _channel?.sink.add(json.encode(message));
    _logger.info('Sent prompt to $agentId');
  }
}