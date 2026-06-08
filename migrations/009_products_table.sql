-- Migration: Add products table for product catalogue management
-- Date: 2026-06-08
-- Phase: 3 (Business Engine)

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,

    -- Core fields
    name VARCHAR(200) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category VARCHAR(100) NOT NULL DEFAULT 'saas',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    price FLOAT NOT NULL DEFAULT 0.0,

    -- Deployment
    deployment_url VARCHAR(1000),
    source_opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE SET NULL,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_products_created_at ON products(created_at DESC);

CREATE OR REPLACE FUNCTION update_products_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER products_updated_at_trigger
    BEFORE UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION update_products_updated_at();

COMMENT ON TABLE products IS 'Product catalogue — MVPs and services built by Béa';
COMMENT ON COLUMN products.status IS 'active | inactive | deploying | deployed';
