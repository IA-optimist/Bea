-- Migration: Add opportunity_analyses table for feasibility analysis results
-- Date: 2026-04-08
-- Phase: 3 (Business Engine - P3.2)

CREATE TABLE IF NOT EXISTS opportunity_analyses (
    id SERIAL PRIMARY KEY,
    
    -- Link to opportunity
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    
    -- Analysis metadata
    analyzed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    analysis_duration_seconds INTEGER,  -- How long the analysis took
    
    -- Cognition metadata
    mission_id VARCHAR(50),  -- JarvisMax mission ID (if triggered via cognition)
    confidence_score FLOAT,  -- Self-confidence score (0.0-1.0)
    cognition_reasoning TEXT,  -- Reasoning from confidence scorer
    
    -- Technical feasibility
    tech_stack JSONB,  -- ["python", "fastapi", "react", "postgresql"]
    dependencies JSONB,  -- ["stripe", "sendgrid", "openai"]
    complexity_score INTEGER,  -- 1-10 (1=trivial, 10=extremely complex)
    estimated_hours INTEGER,  -- Time to build MVP
    
    -- MVP scope
    mvp_features JSONB,  -- ["user_auth", "dashboard", "api", "payments"]
    nice_to_have_features JSONB,  -- Future enhancements
    out_of_scope JSONB,  -- Features to exclude from MVP
    
    -- Risk assessment
    technical_risks JSONB,  -- ["API rate limits", "Complex auth flow"]
    mitigation_strategies JSONB,  -- Risk mitigation approaches
    
    -- Recommendations
    recommendation TEXT,  -- "BUILD", "SKIP", "NEEDS_MORE_RESEARCH"
    reasoning TEXT,  -- Why this recommendation?
    market_fit_score FLOAT,  -- 0-100 (alignment with market demand)
    
    -- Full analysis (raw output)
    full_analysis TEXT,  -- Complete analysis text
    raw_output JSONB,  -- Structured data from analyzer
    
    -- Status
    approved BOOLEAN DEFAULT FALSE,  -- Manual approval for MVP generation
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_opportunity_analyses_opportunity_id ON opportunity_analyses(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_analyses_analyzed_at ON opportunity_analyses(analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_analyses_recommendation ON opportunity_analyses(recommendation);
CREATE INDEX IF NOT EXISTS idx_opportunity_analyses_complexity_score ON opportunity_analyses(complexity_score);
CREATE INDEX IF NOT EXISTS idx_opportunity_analyses_approved ON opportunity_analyses(approved);

-- Foreign key index for JOIN performance
CREATE INDEX IF NOT EXISTS idx_opportunity_analyses_opportunity_fk ON opportunity_analyses(opportunity_id);

-- Trigger for updated_at
CREATE OR REPLACE FUNCTION update_opportunity_analyses_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER opportunity_analyses_updated_at_trigger
    BEFORE UPDATE ON opportunity_analyses
    FOR EACH ROW
    EXECUTE FUNCTION update_opportunity_analyses_updated_at();

-- Comments
COMMENT ON TABLE opportunity_analyses IS 'Feasibility analysis results for SaaS opportunities (P3.2)';
COMMENT ON COLUMN opportunity_analyses.complexity_score IS '1=trivial, 5=moderate, 10=extremely complex';
COMMENT ON COLUMN opportunity_analyses.recommendation IS 'BUILD (proceed to MVP), SKIP (not viable), NEEDS_MORE_RESEARCH';
COMMENT ON COLUMN opportunity_analyses.confidence_score IS 'Self-confidence score from cognition system (0.0-1.0)';
COMMENT ON COLUMN opportunity_analyses.approved IS 'Manual approval required before MVP generation (safety gate)';
