import 'package:flutter/material.dart';
import 'package:orchestrate_mobile/models/workflow.dart';

class WorkflowCard extends StatelessWidget {
  final Workflow workflow;
  final VoidCallback onTap;
  final Function(String) onAction;

  const WorkflowCard({
    Key? key,
    required this.workflow,
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
              // Header with status and framework
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
                  // Workflow name and framework
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          workflow.name,
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        Text(
                          _getFrameworkLabel(),
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: Colors.grey[600],
                          ),
                        ),
                      ],
                    ),
                  ),
                  // Progress indicator
                  if (workflow.status == 'running')
                    Column(
                      children: [
                        SizedBox(
                          width: 40,
                          height: 40,
                          child: CircularProgressIndicator(
                            value: workflow.progress,
                            strokeWidth: 3,
                            backgroundColor: Colors.grey[300],
                            valueColor: AlwaysStoppedAnimation<Color>(_getStatusColor()),
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${(workflow.progress * 100).toInt()}%',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                ],
              ),
              
              const SizedBox(height: 12),
              
              // Description
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  workflow.description,
                  style: Theme.of(context).textTheme.bodySmall,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              
              const SizedBox(height: 12),
              
              // Agents count
              Row(
                children: [
                  Icon(
                    Icons.robot,
                    size: 16,
                    color: Colors.grey[600],
                  ),
                  const SizedBox(width: 4),
                  Text(
                    '${workflow.agentIds.length} agents',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const Spacer(),
                  if (workflow.startTime != null)
                    Text(
                      _formatDuration(workflow.startTime!),
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Colors.grey[600],
                      ),
                    ),
                ],
              ),
              
              const SizedBox(height: 12),
              
              // Actions
              Row(
                children: [
                  if (workflow.status == 'pending')
                    _buildActionButton(
                      context,
                      'Start',
                      Icons.play_arrow,
                      Colors.green,
                      () => onAction('start'),
                    ),
                  if (workflow.status == 'running')
                    _buildActionButton(
                      context,
                      'Stop',
                      Icons.stop,
                      Colors.red,
                      () => onAction('stop'),
                    ),
                  if (workflow.status == 'error')
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
    switch (workflow.status) {
      case 'running':
        return Colors.blue;
      case 'completed':
        return Colors.green;
      case 'error':
        return Colors.red;
      case 'pending':
        return Colors.orange;
      default:
        return Colors.grey;
    }
  }

  IconData _getStatusIcon() {
    switch (workflow.status) {
      case 'running':
        return Icons.play_arrow;
      case 'completed':
        return Icons.check_circle;
      case 'error':
        return Icons.error;
      case 'pending':
        return Icons.schedule;
      default:
        return Icons.circle;
    }
  }

  String _getFrameworkLabel() {
    switch (workflow.framework) {
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
        return workflow.framework.toUpperCase();
    }
  }

  String _formatDuration(DateTime startTime) {
    final now = DateTime.now();
    final difference = now.difference(startTime);
    
    if (difference.inMinutes < 1) {
      return 'Just now';
    } else if (difference.inMinutes < 60) {
      return '${difference.inMinutes}m ago';
    } else if (difference.inHours < 24) {
      return '${difference.inHours}h ago';
    } else {
      return '${difference.inDays}d ago';
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