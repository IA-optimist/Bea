-- Migration 008: Add final_output column to missions table
-- This column stores the final result of mission execution
-- Required for proper persistence of mission results

ALTER TABLE missions ADD COLUMN final_output TEXT DEFAULT '';
ALTER TABLE missions ADD COLUMN summary TEXT DEFAULT '';
ALTER TABLE missions ADD COLUMN agents_selected TEXT DEFAULT '[]';
ALTER TABLE missions ADD COLUMN domain TEXT DEFAULT 'general';
ALTER TABLE missions ADD COLUMN execution_trace TEXT DEFAULT '[]';
ALTER TABLE missions ADD COLUMN decision_trace TEXT DEFAULT '{}';
ALTER TABLE missions ADD COLUMN risk_score INTEGER DEFAULT 0;
ALTER TABLE missions ADD COLUMN complexity TEXT DEFAULT 'medium';
ALTER TABLE missions ADD COLUMN error TEXT DEFAULT '';
