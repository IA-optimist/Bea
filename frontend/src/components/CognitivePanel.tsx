
import { Brain, CheckCircle, Circle, Loader2 } from 'lucide-react';
import { Card } from './Card';

interface Step {
  id: string;
  title: string;
  status: 'pending' | 'active' | 'completed';
}

interface Agent {
  name: string;
  status: 'active' | 'idle';
  progress?: string;
}

interface CognitivePanelProps {
  plan?: Step[];
  agents?: Agent[];
  reasoning?: string;
  isVisible?: boolean;
}

export function CognitivePanel({ 
  plan = [], 
  agents = [], 
  reasoning,
  isVisible = true 
}: CognitivePanelProps) {
  if (!isVisible) return null;

  return (
    <div className="space-y-4">
      {/* Plan Section */}
      {plan.length > 0 && (
        <Card className="p-4">
          <div className="flex items-center gap-2 mb-4">
            <Brain className="w-5 h-5 text-blue-500" />
            <h3 className="font-semibold text-lg">Plan d'Exécution</h3>
          </div>
          <div className="space-y-2">
            {plan.map((step, idx) => (
              <div 
                key={step.id} 
                className="flex items-start gap-3 p-2 rounded hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                <div className="flex-shrink-0 mt-0.5">
                  {step.status === 'completed' && (
                    <CheckCircle className="w-5 h-5 text-green-500" />
                  )}
                  {step.status === 'active' && (
                    <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
                  )}
                  {step.status === 'pending' && (
                    <Circle className="w-5 h-5 text-gray-400" />
                  )}
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-500">
                      {idx + 1}.
                    </span>
                    <span className={`text-sm ${
                      step.status === 'completed' ? 'text-gray-600 dark:text-gray-400' :
                      step.status === 'active' ? 'text-blue-600 dark:text-blue-400 font-medium' :
                      'text-gray-500'
                    }`}>
                      {step.title}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Agents Section */}
      {agents.length > 0 && (
        <Card className="p-4">
          <h3 className="font-semibold text-lg mb-4">Agents Actifs</h3>
          <div className="space-y-3">
            {agents.map((agent) => (
              <div 
                key={agent.name}
                className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded"
              >
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${
                    agent.status === 'active' 
                      ? 'bg-green-500 animate-pulse' 
                      : 'bg-gray-400'
                  }`} />
                  <span className="font-medium">{agent.name}</span>
                </div>
                {agent.progress && (
                  <span className="text-sm text-gray-500">{agent.progress}</span>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Reasoning Section */}
      {reasoning && (
        <Card className="p-4">
          <h3 className="font-semibold text-lg mb-2">Raisonnement</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
            {reasoning}
          </p>
        </Card>
      )}
    </div>
  );
}
