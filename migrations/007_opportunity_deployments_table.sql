-- P3.4 — Opportunity Deployments Table
-- Tracks deployed MVPs (VPS location, status, uptime)

-- Create update_updated_at_column function if not exists
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TABLE IF NOT EXISTS opportunity_deployments (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    
    -- GitHub
    repo_name VARCHAR(255) NOT NULL,
    repo_url TEXT NOT NULL,
    clone_url TEXT,
    html_url TEXT,
    
    -- Deployment
    deployed_at TIMESTAMP DEFAULT NOW(),
    deploy_path TEXT NOT NULL,
    subdomain VARCHAR(255) NOT NULL UNIQUE,
    url TEXT NOT NULL,
    
    -- Status
    status VARCHAR(50) DEFAULT 'deploying',  -- deploying, live, down, removed
    last_health_check TIMESTAMP,
    uptime_percent DECIMAL(5,2) DEFAULT 100.0,
    
    -- Metadata
    deploy_duration_seconds INTEGER,
    docker_image_tag VARCHAR(100),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    removed_at TIMESTAMP
);

-- Indexes
CREATE INDEX idx_opportunity_deployments_opportunity_id ON opportunity_deployments(opportunity_id);
CREATE INDEX idx_opportunity_deployments_status ON opportunity_deployments(status);
CREATE INDEX idx_opportunity_deployments_subdomain ON opportunity_deployments(subdomain);
CREATE INDEX idx_opportunity_deployments_deployed_at ON opportunity_deployments(deployed_at DESC);

-- Auto-update updated_at
CREATE TRIGGER update_opportunity_deployments_updated_at
BEFORE UPDATE ON opportunity_deployments
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- Add deployed column to opportunities
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS deployed BOOLEAN DEFAULT FALSE;

COMMENT ON TABLE opportunity_deployments IS 'P3.4 — Tracks deployed MVPs on VPS';
COMMENT ON COLUMN opportunity_deployments.status IS 'deploying, live, down, removed';
COMMENT ON COLUMN opportunity_deployments.uptime_percent IS '0-100% uptime (last 30 days)';
