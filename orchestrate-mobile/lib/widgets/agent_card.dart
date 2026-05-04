import 'package:flutter/material.dart';
import 'package:orchestrate_mobile/models/agent.dart';

class AgentCard extends StatelessWidget {
  final Agent agent;
  final VoidCallback onTap;
  final Function(String) onAction;

  const AgentCard({
    Key? key,
    required this.agent,
    required this.onTap,
    required this.onAction,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 2,
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header with status and progress
              Row(
                children: [
                  // Status indicator
                  Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: _getStatusColor(),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(
                      _getStatusIcon(),
                      color: Colors.white,
                      size: 16,
                    ),
                  ),
                  const SizedBox(width: 12),
                  // Agent name and type
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          agent.name,
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        Text(
                          _getTypeLabel(),
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: Colors.grey[600],
                          ),
                        ),
                      ],
                    ),
                  ),
                  // Progress indicator
                  if (agent.status == 'running')
                    Column(
                      children: [
                        SizedBox(
                          width: 40,
                          height: 40,
                          child: CircularProgressIndicator(
                            value: agent.progress,
                            strokeWidth: 3,
                            backgroundColor: Colors.grey[300],
                            valueColor: AlwaysStoppedAnimation<Color>(_getStatusColor()),
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${(agent.progress * 100).toInt()}%',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                ],
              ),
              
              const SizedBox(height: 12),
              
              // Message
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  agent.message,
                  style: Theme.of(context).textTheme.bodySmall,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              
              const SizedBox(height: 12),
              
              // Actions
              Row(
                children: [
                  if (agent.status == 'running')
                    _buildActionButton(
                      context,
                      'Stop',
                      Icons.stop,
                      Colors.red,
                      () => onAction('stop'),
                    ),
                  if (agent.status == 'idle')
                    _buildActionButton(
                      context,
                      'Start',
                      Icons.play_arrow,
                      Colors.green,
                      () => onAction('start'),
                    ),
                  if (agent.status == 'error')
                    _buildActionButton(
                      context,
                      'Restart',
                      Icons.refresh,
                      Colors.orange,
                      () => onAction('restart'),
                    ),
                  const Spacer(),
                  _buildActionButton(
                    context,
                    'Details',
                    Icons.info,
                    Colors.blue,
                    onTap,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Color _getStatusColor() {
    switch (agent.status) {
      case 'running':
        return Colors.blue;
      case 'completed':
        return Colors.green;
      case 'error':
        return Colors.red;
      case 'idle':
        return Colors.grey;
      default:
        return Colors.grey;
    }
  }

  IconData _getStatusIcon() {
    switch (agent.status) {
      case 'running':
        return Icons.play_arrow;
      case 'completed':
        return Icons.check_circle;
      case 'error':
        return Icons.error;
      case 'idle':
        return Icons.pause;
      default:
        return Icons.circle;
    }
  }

  String _getTypeLabel() {
    switch (agent.type) {
      case 'langchain':
        return 'LangChain';
      case 'autogen':
        return 'AutoGen';
      case 'crewai':
        return 'CrewAI';
      case 'llamaindex':
        return 'LlamaIndex';
      case 'haystack':
        return 'Haystack';
      case 'kimi':
        return 'Kimi';
      default:
        return agent.type.toUpperCase();
    }
  }

  Widget _buildActionButton(
    BuildContext context,
    String label,
    IconData icon,
    Color color,
    VoidCallback onPressed,
  ) {
    return TextButton.icon(
      icon: Icon(icon, size: 16),
      label: Text(label),
      style: TextButton.styleFrom(
        foregroundColor: color,
        padding: const EdgeInsets.symmetric(horizontal: 8),
      ),
      onPressed: onPressed,
    );
  }
}