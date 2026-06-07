-- Migration 004: Multi-Project Foundation
-- BeaMax Phase 2.1 - Project isolation architecture
-- PostgreSQL 13+ compatible
-- Run date: 2026-04-08

BEGIN;

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create projects table
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    config JSONB DEFAULT '{}'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE projects IS 'Project isolation - each project represents an autonomous mission scope (SaaS Gen, Bug Bounty, etc.)';
COMMENT ON COLUMN projects.config IS 'Project-specific configuration (agent preferences, budgets, routing rules)';
COMMENT ON COLUMN projects.metadata IS 'Extended metadata (tags, owner, priority, etc.)';

-- Add project_id to canonical_missions (nullable for backward compatibility)
ALTER TABLE canonical_missions 
ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;

COMMENT ON COLUMN canonical_missions.project_id IS 'Project scope for mission isolation';

-- Add project_id to vault_memory (nullable for backward compatibility)
ALTER TABLE vault_memory 
ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;

COMMENT ON COLUMN vault_memory.project_id IS 'Project scope for memory isolation';

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
CREATE INDEX IF NOT EXISTS idx_projects_active ON projects(is_active);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_missions_project_id ON canonical_missions(project_id);
CREATE INDEX IF NOT EXISTS idx_vault_project_id ON vault_memory(project_id);

-- Create composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_missions_project_status ON canonical_missions(project_id, status);
CREATE INDEX IF NOT EXISTS idx_vault_project_tags ON vault_memory(project_id, tags);

-- Create updated_at trigger for projects
CREATE OR REPLACE FUNCTION update_projects_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_projects_updated_at();

-- Seed default projects
INSERT INTO projects (name, description, config, metadata) VALUES
(
    'saas-generator',
    'Autonomous SaaS product generation and deployment pipeline',
    '{"priority": "high", "auto_deploy": true, "budget_daily_usd": 50}'::jsonb,
    '{"tags": ["business", "automation", "revenue"], "owner": "business_engine"}'::jsonb
),
(
    'bug-bounty-hunter',
    'Automated vulnerability discovery and bug bounty submissions',
    '{"priority": "high", "auto_submit": true, "min_severity": "medium"}'::jsonb,
    '{"tags": ["security", "revenue", "redteam"], "owner": "hexstrike"}'::jsonb
),
(
    'blue-team-defense',
    'Continuous security monitoring and incident response',
    '{"priority": "critical", "alert_threshold": "medium", "auto_respond": true}'::jsonb,
    '{"tags": ["security", "monitoring", "blueteam"], "owner": "soc_service"}'::jsonb
),
(
    'comptabilite-fiscale',
    'Automated accounting, tax optimization, and compliance',
    '{"priority": "medium", "auto_categorize": true, "tax_jurisdiction": "FR"}'::jsonb,
    '{"tags": ["finance", "compliance", "tax"], "owner": "tax_optimizer"}'::jsonb
),
(
    'bizgen-intelligence',
    'Market research, opportunity discovery, and business intelligence',
    '{"priority": "medium", "scan_frequency_hours": 24, "min_opportunity_score": 0.7}'::jsonb,
    '{"tags": ["research", "business", "intelligence"], "owner": "data_intelligence"}'::jsonb
),
(
    'cash-machine-ops',
    'Revenue operations, metrics tracking, and financial optimization',
    '{"priority": "high", "track_all_revenue": true, "reporting_frequency": "daily"}'::jsonb,
    '{"tags": ["finance", "operations", "metrics"], "owner": "cash_machine"}'::jsonb
)
ON CONFLICT (name) DO NOTHING;

-- Create migration history table if it doesn't exist
CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    execution_time_ms INTEGER
);

-- Record this migration
INSERT INTO migration_history (migration_name, success, execution_time_ms)
VALUES ('004_multi_project_foundation', true, 0)
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

-- Verify migration success
SELECT 
    'Migration 004 completed successfully' AS status,
    COUNT(*) AS projects_created
FROM projects;
