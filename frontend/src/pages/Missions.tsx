import { useState, useEffect } from 'react';
import { PlusCircle, Brain, History } from 'lucide-react';
import { Button } from '../components/Button';
import { MissionInput } from '../components/MissionInput';
import { CognitivePanel } from '../components/CognitivePanel';
import { StructuredOutput } from '../components/StructuredOutput';
import { MissionHistory } from '../components/MissionHistory';
import { apiClient } from '../api/client';

interface Mission {
  id: string;
  title: string;
  date: string;
  status: 'completed' | 'failed' | 'running';
  confidenceScore?: number;
  plan?: any[];
  agents?: any[];
  reasoning?: string;
  output?: any[];
}

export default function Missions() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [activeMission, setActiveMission] = useState<Mission | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [showHistory, setShowHistory] = useState(true);

  // Load missions on mount
  useEffect(() => {
    loadMissions();
  }, []);

  const loadMissions = async () => {
    try {
      // TODO: Replace with actual API call
      // const response = await apiClient.get('/api/v3/missions');
      // setMissions(response.data);
      
      // Mock data for now
      setMissions([
        {
          id: '1',
          title: 'Analyse architecture système',
          date: new Date().toISOString(),
          status: 'completed',
          confidenceScore: 0.92,
        },
        {
          id: '2',
          title: 'Bug fix authentification',
          date: new Date(Date.now() - 3600000).toISOString(),
          status: 'completed',
          confidenceScore: 0.87,
        },
      ]);
    } catch (error) {
      console.error('Failed to load missions:', error);
    }
  };

  const handleSubmitMission = async (message: string) => {
    setIsExecuting(true);
    
    try {
      // Create new mission
      const newMission: Mission = {
        id: Date.now().toString(),
        title: message.slice(0, 50) + (message.length > 50 ? '...' : ''),
        date: new Date().toISOString(),
        status: 'running',
      };
      
      setMissions([newMission, ...missions]);
      setActiveMission(newMission);

      // Call API
      const response = await apiClient.post('/api/v3/chat', {
        message,
        project_id: 1,
      });

      // Update mission with results
      const updatedMission: Mission = {
        ...newMission,
        status: 'completed',
        confidenceScore: response.data.confidence_score,
        reasoning: response.data.cognition_reasoning,
        output: [
          {
            type: 'summary',
            title: 'Résumé',
            content: response.data.response.slice(0, 200),
          },
          {
            type: 'explanation',
            title: 'Explication Détaillée',
            content: response.data.response,
          },
        ],
        // Mock plan for demo
        plan: [
          { id: '1', title: 'Analyser la demande', status: 'completed' },
          { id: '2', title: 'Rechercher informations', status: 'completed' },
          { id: '3', title: 'Produire réponse', status: 'completed' },
          { id: '4', title: 'Vérifier cohérence', status: 'completed' },
        ],
        agents: [
          { name: 'Research Agent', status: 'idle' },
          { name: 'Planner Agent', status: 'idle' },
        ],
      };

      setActiveMission(updatedMission);
      setMissions([updatedMission, ...missions.filter(m => m.id !== newMission.id)]);
      
    } catch (error) {
      console.error('Mission failed:', error);
      // Handle error
    } finally {
      setIsExecuting(false);
    }
  };

  const handleSelectMission = (id: string) => {
    const mission = missions.find(m => m.id === id);
    if (mission) {
      setActiveMission(mission);
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      {/* Sidebar */}
      <div className={`${
        showHistory ? 'w-80' : 'w-0'
      } border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-800 transition-all duration-300 overflow-hidden`}>
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <Button
            onClick={() => setActiveMission(null)}
            className="w-full flex items-center justify-center gap-2"
          >
            <PlusCircle className="w-4 h-4" />
            Nouvelle Mission
          </Button>
        </div>
        <div className="p-4 overflow-y-auto" style={{ height: 'calc(100vh - 80px)' }}>
          <MissionHistory
            missions={missions}
            activeMissionId={activeMission?.id}
            onSelectMission={handleSelectMission}
          />
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Brain className="w-6 h-6 text-blue-500" />
            <h1 className="text-xl font-bold">
              {activeMission ? activeMission.title : 'Nouvelle Mission'}
            </h1>
          </div>
          <Button
            variant="ghost"
            onClick={() => setShowHistory(!showHistory)}
            className="flex items-center gap-2"
          >
            <History className="w-4 h-4" />
            {showHistory ? 'Masquer' : 'Historique'}
          </Button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-5xl mx-auto space-y-6">
            {/* Mission Input */}
            {!activeMission && (
              <MissionInput 
                onSubmit={handleSubmitMission}
                isLoading={isExecuting}
              />
            )}

            {/* Active Mission Display */}
            {activeMission && (
              <>
                {/* Cognitive Panel */}
                {(activeMission.plan || activeMission.agents || activeMission.reasoning) && (
                  <CognitivePanel
                    plan={activeMission.plan}
                    agents={activeMission.agents}
                    reasoning={activeMission.reasoning}
                  />
                )}

                {/* Structured Output */}
                {activeMission.output && (
                  <StructuredOutput
                    sections={activeMission.output}
                    confidenceScore={activeMission.confidenceScore}
                    missionId={activeMission.id}
                  />
                )}

                {/* New Mission Button */}
                {activeMission.status === 'completed' && (
                  <div className="flex justify-center pt-4">
                    <Button
                      onClick={() => setActiveMission(null)}
                      className="flex items-center gap-2"
                    >
                      <PlusCircle className="w-4 h-4" />
                      Nouvelle Mission
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
