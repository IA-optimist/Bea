import React, { useState } from 'react';
import { Send, Loader2 } from 'lucide-react';
import { Button } from './Button';

interface MissionInputProps {
  onSubmit: (message: string) => Promise<void>;
  isLoading?: boolean;
}

export function MissionInput({ onSubmit, isLoading = false }: MissionInputProps) {
  const [message, setMessage] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim() || isLoading) return;
    
    await onSubmit(message);
    setMessage('');
  };

  return (
    <form onSubmit={handleSubmit} className="relative">
      <div className="flex items-end gap-2 p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSubmit(e);
            }
          }}
          placeholder="Décrivez votre mission... (Ex: 'Analyse ce repo', 'Crée une stratégie marketing')"
          className="flex-1 resize-none bg-transparent border-none focus:outline-none focus:ring-0 min-h-[60px] max-h-[200px]"
          rows={2}
          disabled={isLoading}
        />
        <Button
          type="submit"
          disabled={!message.trim() || isLoading}
          className="flex items-center gap-2 px-4 py-2"
        >
          {isLoading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Exécution...</span>
            </>
          ) : (
            <>
              <Send className="w-4 h-4" />
              <span>Lancer Mission</span>
            </>
          )}
        </Button>
      </div>
    </form>
  );
}
