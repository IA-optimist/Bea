-- BeaMax Database Schema
-- PostgreSQL 16+

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search

-- Core tables

-- Modules table
CREATE TABLE IF NOT EXISTS modules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    version VARCHAR(20),
    status VARCHAR(20) DEFAULT 'stopped',
    started_at TIMESTAMP WITH TIME ZONE,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tasks table
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    module_name VARCHAR(100) NOT NULL REFERENCES modules(name),
    action VARCHAR(100) NOT NULL,
    params JSONB,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, completed, failed
    result JSONB,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Revenue table
CREATE TABLE IF NOT EXISTS revenue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    module_name VARCHAR(100) NOT NULL REFERENCES modules(name),
    date DATE NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    customers INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Metrics table
CREATE TABLE IF NOT EXISTS metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    module_name VARCHAR(100) NOT NULL REFERENCES modules(name),
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(10, 2) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Business Engine: Opportunities
CREATE TABLE IF NOT EXISTS opportunities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    description TEXT,
    source VARCHAR(50),
    score DECIMAL(5, 2),
    tags TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Business Engine: Products
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    opportunity_id UUID REFERENCES opportunities(id),
    status VARCHAR(20) DEFAULT 'draft',  -- draft, built, deployed, live
    mrr DECIMAL(10, 2) DEFAULT 0.00,
    customers INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deployed_at TIMESTAMP WITH TIME ZONE
);

-- SOC Service: Clients
CREATE TABLE IF NOT EXISTS soc_clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_name VARCHAR(200) NOT NULL,
    plan VARCHAR(50) NOT NULL,
    monthly_fee DECIMAL(10, 2) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- SOC Service: Alerts
CREATE TABLE IF NOT EXISTS soc_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES soc_clients(id),
    severity VARCHAR(20) NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    source VARCHAR(50),
    status VARCHAR(20) DEFAULT 'new',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- Tax Optimizer: Reports
CREATE TABLE IF NOT EXISTS tax_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email VARCHAR(255),
    revenue DECIMAL(12, 2),
    expenses DECIMAL(12, 2),
    report JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agent Marketplace: Agents
CREATE TABLE IF NOT EXISTS marketplace_agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    creator_id UUID,
    price DECIMAL(10, 2),
    installs INTEGER DEFAULT 0,
    revenue DECIMAL(10, 2) DEFAULT 0.00,
    rating DECIMAL(3, 2) DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agent Marketplace: Purchases
CREATE TABLE IF NOT EXISTS marketplace_purchases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID REFERENCES marketplace_agents(id),
    buyer_email VARCHAR(255),
    amount DECIMAL(10, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_tasks_module ON tasks(module_name);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created ON tasks(created_at DESC);
CREATE INDEX idx_revenue_module ON revenue(module_name);
CREATE INDEX idx_revenue_date ON revenue(date DESC);
CREATE INDEX idx_metrics_module ON metrics(module_name);
CREATE INDEX idx_metrics_timestamp ON metrics(timestamp DESC);
CREATE INDEX idx_opportunities_score ON opportunities(score DESC);
CREATE INDEX idx_products_status ON products(status);
CREATE INDEX idx_soc_alerts_client ON soc_alerts(client_id);
CREATE INDEX idx_soc_alerts_severity ON soc_alerts(severity);
CREATE INDEX idx_soc_alerts_status ON soc_alerts(status);
CREATE INDEX idx_marketplace_agents_revenue ON marketplace_agents(revenue DESC);

-- Insert initial modules
INSERT INTO modules (name, description, version, status) VALUES
    ('business_engine', 'Autonomous SaaS generation pipeline', '1.0.0', 'stopped'),
    ('hexstrike', 'Automated bug bounty hunting', '2.0.0', 'stopped'),
    ('tax_optimizer', 'Legal tax optimization service', '1.0.0', 'stopped'),
    ('soc_service', 'Security Operations Center as a Service', '1.0.0', 'stopped'),
    ('data_intelligence', 'Market research & competitive analysis', '1.0.0', 'stopped'),
    ('agent_marketplace', 'AI agent marketplace platform', '1.0.0', 'stopped')
ON CONFLICT (name) DO NOTHING;

-- Done
SELECT 'BeaMax database initialized successfully' AS status;
