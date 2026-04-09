
import { FileText, Lightbulb, Code, TrendingUp } from 'lucide-react';
import { Card } from './Card';
import { Badge } from './Badge';

interface OutputSection {
  type: 'summary' | 'explanation' | 'plan' | 'recommendations' | 'code' | 'insights';
  title: string;
  content: string;
}

interface StructuredOutputProps {
  sections: OutputSection[];
  confidenceScore?: number;
  missionId?: string;
}

const SectionIcon = ({ type }: { type: OutputSection['type'] }) => {
  const iconClass = "w-5 h-5";
  switch (type) {
    case 'summary': return <FileText className={iconClass} />;
    case 'insights': return <Lightbulb className={iconClass} />;
    case 'code': return <Code className={iconClass} />;
    case 'recommendations': return <TrendingUp className={iconClass} />;
    default: return <FileText className={iconClass} />;
  }
};

export function StructuredOutput({ 
  sections, 
  confidenceScore,
  missionId 
}: StructuredOutputProps) {
  return (
    <Card className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-xl font-bold">Résultat de Mission</h2>
        {confidenceScore !== undefined && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">Confiance:</span>
            <Badge variant={
              confidenceScore >= 0.8 ? 'success' :
              confidenceScore >= 0.6 ? 'warning' :
              'error'
            }>
              {(confidenceScore * 100).toFixed(0)}%
            </Badge>
          </div>
        )}
      </div>

      {/* Sections */}
      <div className="space-y-6">
        {sections.map((section, idx) => (
          <div key={idx} className="space-y-2">
            <div className="flex items-center gap-2">
              <SectionIcon type={section.type} />
              <h3 className="font-semibold text-lg capitalize">{section.title}</h3>
            </div>
            <div className="pl-7">
              {section.type === 'code' ? (
                <pre className="bg-gray-50 dark:bg-gray-900 p-4 rounded overflow-x-auto">
                  <code className="text-sm">{section.content}</code>
                </pre>
              ) : (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  {section.content.split('\n').map((line, i) => (
                    <p key={i} className="mb-2">{line}</p>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      {missionId && (
        <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
          <span className="text-xs text-gray-500">Mission ID: {missionId}</span>
        </div>
      )}
    </Card>
  );
}
