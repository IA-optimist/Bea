-- Migration 003: Business & Finance Tables
-- JarvisMax Phase 1 - Autonomous business engine foundation
-- PostgreSQL 13+ compatible
-- Run date: 2026-04-10

BEGIN;

-- Create business_opportunities table
CREATE TABLE IF NOT EXISTS business_opportunities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,  -- 'saas', 'api', 'tool', 'content', etc.
    feasibility_score REAL DEFAULT 0.0,
    revenue_potential_usd INTEGER DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'discovered',  -- discovered, analyzed, in_development, deployed, abandoned
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE business_opportunities IS 'Discovered business opportunities for autonomous generation';
COMMENT ON COLUMN business_opportunities.feasibility_score IS 'Feasibility score 0.0-1.0 (higher = more feasible)';
COMMENT ON COLUMN business_opportunities.revenue_potential_usd IS 'Estimated monthly revenue potential';
COMMENT ON COLUMN business_opportunities.status IS 'Opportunity lifecycle: discovered, analyzed, in_development, deployed, abandoned';

-- Create indexes for business_opportunities
CREATE INDEX IF NOT EXISTS idx_business_opportunities_category ON business_opportunities(category);
CREATE INDEX IF NOT EXISTS idx_business_opportunities_status ON business_opportunities(status);
CREATE INDEX IF NOT EXISTS idx_business_opportunities_feasibility ON business_opportunities(feasibility_score DESC);
CREATE INDEX IF NOT EXISTS idx_business_opportunities_revenue ON business_opportunities(revenue_potential_usd DESC);
CREATE INDEX IF NOT EXISTS idx_business_opportunities_created_at ON business_opportunities(created_at DESC);

-- Create revenue_streams table
CREATE TABLE IF NOT EXISTS revenue_streams (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    opportunity_id UUID REFERENCES business_opportunities(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    revenue_model VARCHAR(100) NOT NULL,  -- 'subscription', 'usage', 'one_time', 'ads', etc.
    amount_usd REAL NOT NULL DEFAULT 0.0,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    period VARCHAR(50) NOT NULL DEFAULT 'monthly',  -- monthly, annual, one_time
    is_recurring BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE revenue_streams IS 'Revenue tracking for autonomous business operations';
COMMENT ON COLUMN revenue_streams.revenue_model IS 'Revenue model: subscription, usage, one_time, ads, affiliate';
COMMENT ON COLUMN revenue_streams.period IS 'Revenue period: monthly, annual, one_time';

-- Create indexes for revenue_streams
CREATE INDEX IF NOT EXISTS idx_revenue_streams_opportunity_id ON revenue_streams(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_revenue_streams_revenue_model ON revenue_streams(revenue_model);
CREATE INDEX IF NOT EXISTS idx_revenue_streams_is_recurring ON revenue_streams(is_recurring);
CREATE INDEX IF NOT EXISTS idx_revenue_streams_created_at ON revenue_streams(created_at DESC);

-- Create deployments table
CREATE TABLE IF NOT EXISTS deployments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    opportunity_id UUID REFERENCES business_opportunities(id) ON DELETE CASCADE,
    deployment_type VARCHAR(50) NOT NULL,  -- 'docker', 'serverless', 'static', 'api'
    url TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, deploying, active, failed, stopped
    health_check_url TEXT,
    last_health_check_at TIMESTAMP WITH TIME ZONE,
    health_status VARCHAR(50) DEFAULT 'unknown',  -- healthy, degraded, down, unknown
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE deployments IS 'Deployment tracking for generated business products';
COMMENT ON COLUMN deployments.status IS 'Deployment status: pending, deploying, active, failed, stopped';
COMMENT ON COLUMN deployments.health_status IS 'Health check status: healthy, degraded, down, unknown';

-- Create indexes for deployments
CREATE INDEX IF NOT EXISTS idx_deployments_opportunity_id ON deployments(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status);
CREATE INDEX IF NOT EXISTS idx_deployments_health_status ON deployments(health_status);
CREATE INDEX IF NOT EXISTS idx_deployments_created_at ON deployments(created_at DESC);

-- Create updated_at triggers
CREATE TRIGGER business_opportunities_updated_at
    BEFORE UPDATE ON business_opportunities
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER revenue_streams_updated_at
    BEFORE UPDATE ON revenue_streams
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER deployments_updated_at
    BEFORE UPDATE ON deployments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Record this migration
INSERT INTO migration_history (migration_name, success, execution_time_ms)
VALUES ('003_business_tables', true, 0)
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

-- Verify migration success
SELECT 
    'Migration 003 completed successfully' AS status,
    COUNT(*) AS total_tables
FROM information_schema.tables
WHERE table_schema = 'public' 
  AND table_name IN ('business_opportunities', 'revenue_streams', 'deployments');
