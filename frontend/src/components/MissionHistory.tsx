
import { Clock, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { Badge } from './Badge';

interface Mission {
  id: string;
  title: string;
  date: string;
  status: 'completed' | 'failed' | 'running';
  confidenceScore?: number;
}

interface MissionHistoryProps {
  missions: Mission[];
  activeMissionId?: string;
  onSelectMission: (id: string) => void;
}

export function MissionHistory({ 
  missions, 
  activeMissionId,
  onSelectMission 
}: MissionHistoryProps) {
  const getStatusIcon = (status: Mission['status']) => {
    const iconClass = "w-4 h-4";
    switch (status) {
      case 'completed': return <CheckCircle className={`${iconClass} text-green-500`} />;
      case 'failed': return <XCircle className={`${iconClass} text-red-500`} />;
      case 'running': return <AlertCircle className={`${iconClass} text-blue-500 animate-pulse`} />;
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (date.toDateString() === today.toDateString()) {
      return `Aujourd'hui ${date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`;
    } else if (date.toDateString() === yesterday.toDateString()) {
      return `Hier ${date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`;
    } else {
      return date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
    }
  };

  return (
    <div className="space-y-1">
      <h3 className="px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
        Missions Passées
      </h3>
      {missions.length === 0 ? (
        <div className="px-3 py-4 text-sm text-gray-500 text-center">
          Aucune mission
        </div>
      ) : (
        <div className="space-y-1">
          {missions.map((mission) => (
            <button
              key={mission.id}
              onClick={() => onSelectMission(mission.id)}
              className={`w-full text-left px-3 py-2 rounded transition-colors ${
                activeMissionId === mission.id
                  ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                  : 'hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
            >
              <div className="flex items-start gap-2">
                <div className="mt-0.5">{getStatusIcon(mission.status)}</div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">
                    {mission.title}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-gray-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatDate(mission.date)}
                    </span>
                    {mission.confidenceScore !== undefined && (
                      <Badge 
                        variant={mission.confidenceScore >= 0.8 ? 'success' : 'warning'}
                        
                      >
                        {(mission.confidenceScore * 100).toFixed(0)}%
                      </Badge>
                    )}
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
