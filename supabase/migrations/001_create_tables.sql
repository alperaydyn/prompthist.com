-- 360 Summarize Database Schema

-- System Prompts table
CREATE TABLE IF NOT EXISTS system_prompts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    version VARCHAR(3) NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User Prompts table
CREATE TABLE IF NOT EXISTS user_prompts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    version VARCHAR(3) NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Customer Runs table (individual prompt runs per customer)
CREATE TABLE IF NOT EXISTS customer_runs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    run_id VARCHAR(20) NOT NULL,
    customer_num VARCHAR(50) NOT NULL,
    input_text TEXT NOT NULL,
    output_text TEXT NOT NULL,
    system_version VARCHAR(3) NOT NULL,
    user_version VARCHAR(3) NOT NULL,
    model VARCHAR(100) NOT NULL,
    elapsed_seconds DECIMAL(10, 2),
    score_completeness INTEGER,
    score_faithfulness INTEGER,
    score_fluency INTEGER,
    score_analysis_quality INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Index for faster lookups
    CONSTRAINT unique_run UNIQUE (run_id, customer_num)
);

-- Test Sessions table (batch test sessions)
CREATE TABLE IF NOT EXISTS test_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id VARCHAR(20) NOT NULL UNIQUE,
    system_version VARCHAR(3) NOT NULL,
    user_version VARCHAR(3) NOT NULL,
    model VARCHAR(100) NOT NULL,
    total_customers INTEGER NOT NULL DEFAULT 0,
    completed_customers INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    avg_completeness DECIMAL(5, 2),
    avg_faithfulness DECIMAL(5, 2),
    avg_fluency DECIMAL(5, 2),
    avg_analysis_quality DECIMAL(5, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Test Results table (individual results within a test session)
CREATE TABLE IF NOT EXISTS test_results (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id VARCHAR(20) NOT NULL REFERENCES test_sessions(session_id) ON DELETE CASCADE,
    customer_num VARCHAR(50) NOT NULL,
    input_text TEXT NOT NULL,
    output_text TEXT NOT NULL,
    score_completeness INTEGER,
    score_faithfulness INTEGER,
    score_fluency INTEGER,
    score_analysis_quality INTEGER,
    elapsed_seconds DECIMAL(10, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Index for faster lookups
    CONSTRAINT unique_test_result UNIQUE (session_id, customer_num)
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_customer_runs_customer ON customer_runs(customer_num);
CREATE INDEX IF NOT EXISTS idx_customer_runs_created ON customer_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_sessions_created ON test_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_results_session ON test_results(session_id);

-- Enable Row Level Security (optional, for future auth)
ALTER TABLE system_prompts ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_prompts ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_results ENABLE ROW LEVEL SECURITY;

-- Create policies for public access (adjust as needed for auth)
CREATE POLICY "Allow public read access" ON system_prompts FOR SELECT USING (true);
CREATE POLICY "Allow public insert access" ON system_prompts FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow public read access" ON user_prompts FOR SELECT USING (true);
CREATE POLICY "Allow public insert access" ON user_prompts FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow public read access" ON customer_runs FOR SELECT USING (true);
CREATE POLICY "Allow public insert access" ON customer_runs FOR INSERT WITH CHECK (true);

CREATE POLICY "Allow public read access" ON test_sessions FOR SELECT USING (true);
CREATE POLICY "Allow public all access" ON test_sessions FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow public read access" ON test_results FOR SELECT USING (true);
CREATE POLICY "Allow public insert access" ON test_results FOR INSERT WITH CHECK (true);
