import 'package:flutter/material.dart';
import 'package:orchestrate_mobile/widgets/agent_card.dart';
import 'package:orchestrate_mobile/services/websocket_service.dart';
import 'package:orchestrate_mobile/models/agent.dart';
import 'package:orchestrate_mobile/models/workflow.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({Key? key}) : super(key: key);

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final WebSocketService _webSocketService = WebSocketService.instance;
  final List<Agent> _agents = [];
  final List<Workflow> _workflows = [];
  bool _isConnected = false;
  
  @override
  void initState() {
    super.initState();
    _initWebSocket();
    _loadData();
  }
  
  void _initWebSocket() {
    _webSocketService.subscribeToConnection(() {
      setState(() {
        _isConnected = _webSocketService.isConnected;
      });
    });
    
    // S'abonner aux mises à jour des agents
    _webSocketService.subscribeToMessages((message) {
      _loadAgents();
    });
    
    // S'abonner aux mises à jour des workflows
    _webSocketService.subscribeToMessageUpdates((update) {
      _loadWorkflows();
    });
    
    // Connecter au WebSocket
    _webSocketService.connect('ws://localhost:8000/ws');
  }
  
  void _loadData() {
    _loadAgents();
    _loadWorkflows();
  }
  
  void _loadAgents() async {
    // Charger les agents via l'API
    try {
      // Implémenter le chargement via ApiService
      setState(() {
        // Simuler des données pour l'instant
        _agents.clear();
        _agents.addAll([
          Agent(
            id: '1',
            name: 'LangChain Agent',
            type: 'langchain',
            status: 'running',
            progress: 0.7,
            message: 'Processing request...',
            model: 'gpt-4',
            config: {},
            lastUpdate: DateTime.now(),
            activeWorkflows: ['research_workflow'],
          ),
          Agent(
            id: '2',
            name: 'AutoGen Agent',
            type: 'autogen',
            status: 'idle',
            progress: 0.0,
            message: 'Ready',
            model: 'claude-3',
            config: {},
            lastUpdate: DateTime.now(),
            activeWorkflows: [],
          ),
        ]);
      });
    } catch (e) {
      print('Error loading agents: $e');
    }
  }
  
  void _loadWorkflows() async {
    // Charger les workflows via l'API
    try {
      setState(() {
        // Simuler des données pour l'instant
        _workflows.clear();
        _workflows.addAll([
          Workflow(
            id: '1',
            name: 'Research Workflow',
            description: 'Multi-agent research analysis',
            agentIds: ['1', '2'],
            status: 'running',
            progress: 0.5,
            steps: [],
            startTime: DateTime.now().subtract(const Duration(minutes: 10)),
            config: {},
            framework: 'langchain',
          ),
        ]);
      });
    } catch (e) {
      print('Error loading workflows: $e');
    }
  }
  
  @override
  void dispose() {
    _webSocketService.disconnect();
    super.dispose();
  }
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Orchestrate Mobile'),
        backgroundColor: Theme.of(context).primaryColor,
        actions: [
          IconButton(
            icon: Icon(_isConnected ? Icons.connected_device : Icons.device_unknown),
            onPressed: () {
              // Afficher l'état de la connexion
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(_isConnected ? 'Connected' : 'Disconnected'),
                ),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          await _loadData();
        },
        child: SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Stats Cards
              _buildStatsCards(),
              
              const SizedBox(height: 24),
              
              // Agents Section
              _buildAgentsSection(),
              
              const SizedBox(height: 24),
              
              // Workflows Section
              _buildWorkflowsSection(),
              
              const SizedBox(height: 24),
              
              // 3D Visualization Button
              _build3DVisualizationButton(),
            ],
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _createNewWorkflow,
        backgroundColor: Theme.of(context).primaryColor,
        child: const Icon(Icons.add),
      ),
    );
  }
  
  Widget _buildStatsCards() {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _buildStatCard(
                'Active Agents',
                _agents.where((a) => a.status == 'running').length.toString(),
                Icons.robot,
                Colors.blue,
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: _buildStatCard(
                'Workflows',
                _workflows.length.toString(),
                Icons.workspaces,
                Colors.green,
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: _buildStatCard(
                'Messages',
                _agents.fold(0, (sum, agent) => sum + agent.activeWorkflows.length).toString(),
                Icons.message,
                Colors.orange,
              ),
            ),
          ],
        ),
      ],
    );
  }
  
  Widget _buildStatCard(String title, String value, IconData icon, Color color) {
    return Card(
      elevation: 4,
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: color, size: 24),
                const SizedBox(width: 8),
                Text(
                  title,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              value,
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
          ],
        ),
      ),
    );
  }
  
  Widget _buildAgentsSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              'Agents',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            TextButton(
              onPressed: _loadAgents,
              child: const Text('Refresh'),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (_agents.isEmpty)
          const Center(
            child: Padding(
              padding: EdgeInsets.all(16.0),
              child: Text('No agents found'),
            ),
          )
        else
          ListView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: _agents.length,
            itemBuilder: (context, index) {
              final agent = _agents[index];
              return AgentCard(
                agent: agent,
                onTap: () => _showAgentDetails(agent),
                onAction: (action) => _handleAgentAction(agent, action),
              );
            },
          ),
      ],
    );
  }
  
  Widget _buildWorkflowsSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              'Workflows',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            TextButton(
              onPressed: _loadWorkflows,
              child: const Text('Refresh'),
            ),
          ],
        ),
        const SizedBox(height: 16),
        if (_workflows.isEmpty)
          const Center(
            child: Padding(
              padding: EdgeInsets.all(16.0),
              child: Text('No workflows found'),
            ),
          )
        else
          ListView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: _workflows.length,
            itemBuilder: (context, index) {
              final workflow = _workflows[index];
              return WorkflowCard(
                workflow: workflow,
                onTap: () => _showWorkflowDetails(workflow),
                onAction: (action) => _handleWorkflowAction(workflow, action),
              );
            },
          ),
      ],
    );
  }
  
  Widget _build3DVisualizationButton() {
    return Card(
      elevation: 4,
      child: InkWell(
        onTap: _navigateTo3DViewer,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.purple,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.view_in_ar,
                  color: Colors.white,
                  size: 24,
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '3D Visualization',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      'View workflows in 3D space',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios),
            ],
          ),
        ),
      ),
    );
  }
  
  void _showAgentDetails(Agent agent) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => AgentDetailScreen(agent: agent),
      ),
    );
  }
  
  void _showWorkflowDetails(Workflow workflow) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => WorkflowDetailScreen(workflow: workflow),
      ),
    );
  }
  
  void _handleAgentAction(Agent agent, String action) {
    switch (action) {
      case 'start':
        _webSocketService.sendAgentCommand(agent.id, 'start', {});
        break;
      case 'stop':
        _webSocketService.sendAgentCommand(agent.id, 'stop', {});
        break;
      case 'restart':
        _webSocketService.sendAgentCommand(agent.id, 'restart', {});
        break;
      case 'delete':
        _deleteAgent(agent);
        break;
    }
  }
  
  void _handleWorkflowAction(Workflow workflow, String action) {
    switch (action) {
      case 'start':
        _webSocketService.startWorkflow(workflow.id, workflow.name, workflow.agentIds, workflow.framework);
        break;
      case 'stop':
        _webSocketService.stopWorkflow(workflow.id);
        break;
      case 'delete':
        _deleteWorkflow(workflow);
        break;
    }
  }
  
  void _createNewWorkflow() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => const CreateWorkflowScreen(),
      ),
    ).then((_) => _loadWorkflows());
  }
  
  void _navigateTo3DViewer() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => const Viewer3DScreen(),
      ),
    );
  }
  
  void _deleteAgent(Agent agent) {
    // Implémenter la suppression via ApiService
    _loadAgents();
  }
  
  void _deleteWorkflow(Workflow workflow) {
    // Implémenter la suppression via ApiService
    _loadWorkflows();
  }
}