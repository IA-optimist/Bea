import 'package:flutter/material.dart';

class CreateWorkflowScreen extends StatefulWidget {
  const CreateWorkflowScreen({Key? key}) : super(key: key);

  @override
  State<CreateWorkflowScreen> createState() => _CreateWorkflowScreenState();
}

class _CreateWorkflowScreenState extends State<CreateWorkflowScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _descriptionController = TextEditingController();
  
  String _selectedFramework = 'langchain';
  String _selectedModel = 'gpt-4';
  bool _isLoading = false;
  
  final List<String> _availableFrameworks = [
    'langchain',
    'autogen',
    'crewai',
    'llamaindex',
    'haystack',
    'kimi',
  ];
  
  final List<String> _availableModels = [
    'gpt-4',
    'gpt-3.5-turbo',
    'claude-3-sonnet',
    'claude-3-opus',
    'gemini-pro',
    'kimi-large',
  ];

  @override
  void dispose() {
    _nameController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Create Workflow'),
        backgroundColor: Theme.of(context).primaryColor,
        actions: [
          TextButton(
            onPressed: _isLoading ? null : _createWorkflow,
            child: const Text('Create'),
          ),
        ],
      ),
      body: Form(
        key: _formKey,
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Basic Information
              Card(
                elevation: 2,
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Basic Information',
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 16),
                      
                      // Name
                      TextFormField(
                        controller: _nameController,
                        decoration: const InputDecoration(
                          labelText: 'Workflow Name',
                          hintText: 'Enter a descriptive name for your workflow',
                        ),
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Please enter a workflow name';
                          }
                          if (value.length < 3) {
                            return 'Name must be at least 3 characters';
                          }
                          return null;
                        },
                      ),
                      
                      const SizedBox(height: 16),
                      
                      // Description
                      TextFormField(
                        controller: _descriptionController,
                        decoration: const InputDecoration(
                          labelText: 'Description',
                          hintText: 'Describe what this workflow will do',
                        ),
                        maxLines: 3,
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Please enter a description';
                          }
                          if (value.length < 10) {
                            return 'Description must be at least 10 characters';
                          }
                          return null;
                        },
                      ),
                    ],
                  ),
                ),
              ),
              
              const SizedBox(height: 24),
              
              // Configuration
              Card(
                elevation: 2,
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Configuration',
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 16),
                      
                      // Framework Selection
                      DropdownButtonFormField<String>(
                        value: _selectedFramework,
                        decoration: const InputDecoration(
                          labelText: 'Framework',
                        ),
                        items: _availableFrameworks.map((framework) {
                          return DropdownMenuItem<String>(
                            value: framework,
                            child: Text(_getFrameworkLabel(framework)),
                          );
                        }).toList(),
                        onChanged: (value) {
                          setState(() {
                            _selectedFramework = value!;
                          });
                        },
                      ),
                      
                      const SizedBox(height: 16),
                      
                      // Model Selection
                      DropdownButtonFormField<String>(
                        value: _selectedModel,
                        decoration: const InputDecoration(
                          labelText: 'Model',
                        ),
                        items: _availableModels.map((model) {
                          return DropdownMenuItem<String>(
                            value: model,
                            child: Text(model.toUpperCase()),
                          );
                        }).toList(),
                        onChanged: (value) {
                          setState(() {
                            _selectedModel = value!;
                          });
                        },
                      ),
                    ],
                  ),
                ),
              ),
              
              const SizedBox(height: 24),
              
              // Agents Selection
              Card(
                elevation: 2,
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            'Agents',
                            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          TextButton(
                            onPressed: _addAgent,
                            child: const Text('Add Agent'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      
                      // Agents List (simulated)
                      Container(
                        height: 100,
                        decoration: BoxDecoration(
                          border: Border.all(color: Colors.grey[300]!),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Center(
                          child: Text(
                            'No agents selected\nTap "Add Agent" to add agents',
                            style: TextStyle(
                              color: Colors.grey,
                              fontSize: 14,
                            ),
                            textAlign: TextAlign.center,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              
              const SizedBox(height: 24),
              
              // Advanced Options
              Card(
                elevation: 2,
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            'Advanced Options',
                            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          IconButton(
                            icon: const Icon(Icons.expand_more),
                            onPressed: () {
                              // Toggle advanced options
                            },
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      
                      // Enable Retry
                      SwitchListTile(
                        title: const Text('Enable Retry on Failure'),
                        subtitle: const Text('Automatically retry failed steps'),
                        value: true,
                        onChanged: (value) {
                          // Handle retry toggle
                        },
                      ),
                      
                      const SizedBox(height: 16),
                      
                      // Timeout
                      TextFormField(
                        decoration: const InputDecoration(
                          labelText: 'Timeout (seconds)',
                          hintText: '300',
                        ),
                        keyboardType: TextInputType.number,
                        initialValue: '300',
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Please enter a timeout value';
                          }
                          final timeout = int.tryParse(value);
                          if (timeout == null || timeout <= 0) {
                            return 'Please enter a valid timeout value';
                          }
                          return null;
                        },
                      ),
                    ],
                  ),
                ),
              ),
              
              const SizedBox(height: 32),
              
              // Create Button
              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  onPressed: _isLoading ? null : _createWorkflow,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Theme.of(context).primaryColor,
                  ),
                  child: _isLoading
                      ? const Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            ),
                            SizedBox(width: 16),
                            Text('Creating...'),
                          ],
                        )
                      : const Text('Create Workflow'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _getFrameworkLabel(String framework) {
    switch (framework) {
      case 'langchain':
        return 'LangChain';
      case 'autogen':
        return 'AutoGen';
      case 'crewai':
        return 'CrewAI';
      case 'llamaindex':
        return 'LlamaIndex';
      case 'haystack':
        return 'HayStack';
      case 'kimi':
        return 'Kimi Agent SDK';
      default:
        return framework.toUpperCase();
    }
  }

  void _addAgent() {
    // Navigate to agent selection screen
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Agent selection not implemented yet')),
    );
  }

  void _createWorkflow() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isLoading = true;
    });

    try {
      // Simulate API call
      await Future.delayed(const Duration(seconds: 2));
      
      // Navigate back to dashboard
      if (mounted) {
        Navigator.pop(context, true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error creating workflow: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }
}