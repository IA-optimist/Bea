-- Migration 008: Add final_output column to missions table
-- This column stores the final result of mission execution
-- Required for proper persistence of mission results

ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS final_output TEXT DEFAULT '';
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS summary TEXT DEFAULT '';
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS agents_selected TEXT DEFAULT '[]';
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS domain TEXT DEFAULT 'general';
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS execution_trace TEXT DEFAULT '[]';
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS decision_trace TEXT DEFAULT '{}';
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS risk_score INTEGER DEFAULT 0;
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS complexity TEXT DEFAULT 'medium';
ALTER TABLE canonical_missions ADD COLUMN IF NOT EXISTS error TEXT DEFAULT '';
