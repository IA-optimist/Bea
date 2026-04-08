-- Migration: Add opportunities table for SaaS opportunity scanner
-- Date: 2026-04-08
-- Phase: 3 (Business Engine)

CREATE TABLE IF NOT EXISTS opportunities (
    id SERIAL PRIMARY KEY,
    
    -- Core fields
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    source VARCHAR(50) NOT NULL,  -- product_hunt, reddit, hackernews, indie_hackers
    url VARCHAR(1000) NOT NULL,
    discovered_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Metrics
    upvotes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    mentions INTEGER DEFAULT 1,
    
    -- Scores (0-100)
    demand_score FLOAT DEFAULT 0.0,
    competition_score FLOAT DEFAULT 0.0,
    feasibility_score FLOAT DEFAULT 0.0,
    monetization_score FLOAT DEFAULT 0.0,
    total_score FLOAT DEFAULT 0.0,
    
    -- Tags & analysis
    tags JSONB DEFAULT '[]'::jsonb,
    pain_points JSONB DEFAULT '[]'::jsonb,
    
    -- Processing status
    analyzed BOOLEAN DEFAULT FALSE,
    mvp_generated BOOLEAN DEFAULT FALSE,
    deployed BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_opportunities_title ON opportunities(title);
CREATE INDEX IF NOT EXISTS idx_opportunities_source ON opportunities(source);
CREATE INDEX IF NOT EXISTS idx_opportunities_discovered_at ON opportunities(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_demand_score ON opportunities(demand_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_monetization_score ON opportunities(monetization_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_total_score ON opportunities(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_analyzed ON opportunities(analyzed);

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_opportunities_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER opportunities_updated_at_trigger
    BEFORE UPDATE ON opportunities
    FOR EACH ROW
    EXECUTE FUNCTION update_opportunities_updated_at();

-- Comments
COMMENT ON TABLE opportunities IS 'SaaS business opportunities discovered by automated scanner (Phase 3)';
COMMENT ON COLUMN opportunities.total_score IS 'Weighted score: demand*0.35 + competition*0.20 + feasibility*0.25 + monetization*0.20';
COMMENT ON COLUMN opportunities.analyzed IS 'TRUE if feasibility analysis completed (P3.2)';
COMMENT ON COLUMN opportunities.mvp_generated IS 'TRUE if MVP code generated (P3.3)';
COMMENT ON COLUMN opportunities.deployed IS 'TRUE if MVP deployed to production (P3.4)';
