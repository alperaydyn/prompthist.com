-- ============================================================================
-- Migration: Add Projects, User Ownership, and Multi-User Support
-- ============================================================================

-- Drop existing policies first (they reference old structure)
DROP POLICY IF EXISTS "Allow public read access" ON system_prompts;
DROP POLICY IF EXISTS "Allow public insert access" ON system_prompts;
DROP POLICY IF EXISTS "Allow public read access" ON user_prompts;
DROP POLICY IF EXISTS "Allow public insert access" ON user_prompts;
DROP POLICY IF EXISTS "Allow public read access" ON customer_runs;
DROP POLICY IF EXISTS "Allow public insert access" ON customer_runs;
DROP POLICY IF EXISTS "Allow public read access" ON test_sessions;
DROP POLICY IF EXISTS "Allow public all access" ON test_sessions;
DROP POLICY IF EXISTS "Allow public read access" ON test_results;
DROP POLICY IF EXISTS "Allow public insert access" ON test_results;

-- ============================================================================
-- PROJECTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS projects (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);

-- ============================================================================
-- PROJECT MEMBERS TABLE (Multi-user support)
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_members (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'viewer' CHECK (role IN ('owner', 'editor', 'viewer')),
    invited_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT unique_project_member UNIQUE (project_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_project_members_project ON project_members(project_id);
CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_id);

-- ============================================================================
-- PROJECT INVITATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_invitations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'viewer' CHECK (role IN ('editor', 'viewer')),
    invited_by UUID NOT NULL REFERENCES auth.users(id),
    token VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'expired', 'cancelled')),
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '7 days'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT unique_pending_invitation UNIQUE (project_id, email, status)
);

CREATE INDEX IF NOT EXISTS idx_project_invitations_token ON project_invitations(token);
CREATE INDEX IF NOT EXISTS idx_project_invitations_email ON project_invitations(email);

-- ============================================================================
-- PROJECT DATA TABLE (Data uploads per project)
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_data (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    file_type VARCHAR(50) NOT NULL, -- 'csv', 'json', 'excel', 'text'
    file_path TEXT, -- For file storage reference
    row_count INTEGER DEFAULT 0,
    column_info JSONB DEFAULT '[]', -- Column names and types
    sample_data JSONB DEFAULT '[]', -- First few rows for preview
    uploaded_by UUID NOT NULL REFERENCES auth.users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_data_project ON project_data(project_id);

-- ============================================================================
-- UPDATE EXISTING TABLES - Add project and user ownership
-- ============================================================================

-- Add columns to system_prompts
ALTER TABLE system_prompts
ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES auth.users(id),
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;

-- Add columns to user_prompts
ALTER TABLE user_prompts
ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES auth.users(id),
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;

-- Add columns to customer_runs
ALTER TABLE customer_runs
ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);

-- Add columns to test_sessions
ALTER TABLE test_sessions
ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);

-- Update unique constraints for prompts (version unique per project, not globally)
ALTER TABLE system_prompts DROP CONSTRAINT IF EXISTS system_prompts_version_key;
ALTER TABLE user_prompts DROP CONSTRAINT IF EXISTS user_prompts_version_key;

-- Create new unique constraints
CREATE UNIQUE INDEX IF NOT EXISTS idx_system_prompts_project_version
ON system_prompts(project_id, version) WHERE project_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_prompts_project_version
ON user_prompts(project_id, version) WHERE project_id IS NOT NULL;

-- Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_system_prompts_project ON system_prompts(project_id);
CREATE INDEX IF NOT EXISTS idx_user_prompts_project ON user_prompts(project_id);
CREATE INDEX IF NOT EXISTS idx_customer_runs_project ON customer_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_test_sessions_project ON test_sessions(project_id);

-- ============================================================================
-- ROW LEVEL SECURITY POLICIES
-- ============================================================================

-- Enable RLS on new tables
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_data ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to check if user has access to a project
CREATE OR REPLACE FUNCTION has_project_access(p_project_id UUID, p_user_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM project_members
        WHERE project_id = p_project_id AND user_id = p_user_id
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to check if user can edit a project
CREATE OR REPLACE FUNCTION can_edit_project(p_project_id UUID, p_user_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM project_members
        WHERE project_id = p_project_id
        AND user_id = p_user_id
        AND role IN ('owner', 'editor')
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to check if user is project owner
CREATE OR REPLACE FUNCTION is_project_owner(p_project_id UUID, p_user_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM project_members
        WHERE project_id = p_project_id
        AND user_id = p_user_id
        AND role = 'owner'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- PROJECTS POLICIES
-- ============================================================================

-- Users can view projects they are members of
CREATE POLICY "Users can view their projects" ON projects
    FOR SELECT USING (
        has_project_access(id, auth.uid())
    );

-- Users can create projects (they become owner)
CREATE POLICY "Users can create projects" ON projects
    FOR INSERT WITH CHECK (
        owner_id = auth.uid()
    );

-- Only owners can update projects
CREATE POLICY "Owners can update projects" ON projects
    FOR UPDATE USING (
        is_project_owner(id, auth.uid())
    );

-- Only owners can delete projects
CREATE POLICY "Owners can delete projects" ON projects
    FOR DELETE USING (
        is_project_owner(id, auth.uid())
    );

-- ============================================================================
-- PROJECT MEMBERS POLICIES
-- ============================================================================

-- Members can view other members in their projects
CREATE POLICY "Members can view project members" ON project_members
    FOR SELECT USING (
        has_project_access(project_id, auth.uid())
    );

-- Owners and editors can add members
CREATE POLICY "Owners can manage members" ON project_members
    FOR INSERT WITH CHECK (
        is_project_owner(project_id, auth.uid())
    );

-- Owners can update member roles
CREATE POLICY "Owners can update members" ON project_members
    FOR UPDATE USING (
        is_project_owner(project_id, auth.uid())
    );

-- Owners can remove members (except themselves)
CREATE POLICY "Owners can remove members" ON project_members
    FOR DELETE USING (
        is_project_owner(project_id, auth.uid()) AND user_id != auth.uid()
    );

-- ============================================================================
-- PROJECT INVITATIONS POLICIES
-- ============================================================================

-- Owners can view invitations
CREATE POLICY "Owners can view invitations" ON project_invitations
    FOR SELECT USING (
        is_project_owner(project_id, auth.uid()) OR
        email = (SELECT email FROM auth.users WHERE id = auth.uid())
    );

-- Owners can create invitations
CREATE POLICY "Owners can create invitations" ON project_invitations
    FOR INSERT WITH CHECK (
        is_project_owner(project_id, auth.uid())
    );

-- Owners can update/cancel invitations
CREATE POLICY "Owners can update invitations" ON project_invitations
    FOR UPDATE USING (
        is_project_owner(project_id, auth.uid())
    );

-- ============================================================================
-- PROJECT DATA POLICIES
-- ============================================================================

-- Members can view project data
CREATE POLICY "Members can view project data" ON project_data
    FOR SELECT USING (
        has_project_access(project_id, auth.uid())
    );

-- Editors and owners can upload data
CREATE POLICY "Editors can upload data" ON project_data
    FOR INSERT WITH CHECK (
        can_edit_project(project_id, auth.uid())
    );

-- Editors and owners can update data
CREATE POLICY "Editors can update data" ON project_data
    FOR UPDATE USING (
        can_edit_project(project_id, auth.uid())
    );

-- Editors and owners can delete data
CREATE POLICY "Editors can delete data" ON project_data
    FOR DELETE USING (
        can_edit_project(project_id, auth.uid())
    );

-- ============================================================================
-- SYSTEM PROMPTS POLICIES
-- ============================================================================

CREATE POLICY "Members can view system prompts" ON system_prompts
    FOR SELECT USING (
        project_id IS NULL OR has_project_access(project_id, auth.uid())
    );

CREATE POLICY "Editors can create system prompts" ON system_prompts
    FOR INSERT WITH CHECK (
        project_id IS NULL OR can_edit_project(project_id, auth.uid())
    );

CREATE POLICY "Editors can update system prompts" ON system_prompts
    FOR UPDATE USING (
        project_id IS NULL OR can_edit_project(project_id, auth.uid())
    );

-- ============================================================================
-- USER PROMPTS POLICIES
-- ============================================================================

CREATE POLICY "Members can view user prompts" ON user_prompts
    FOR SELECT USING (
        project_id IS NULL OR has_project_access(project_id, auth.uid())
    );

CREATE POLICY "Editors can create user prompts" ON user_prompts
    FOR INSERT WITH CHECK (
        project_id IS NULL OR can_edit_project(project_id, auth.uid())
    );

CREATE POLICY "Editors can update user prompts" ON user_prompts
    FOR UPDATE USING (
        project_id IS NULL OR can_edit_project(project_id, auth.uid())
    );

-- ============================================================================
-- CUSTOMER RUNS POLICIES
-- ============================================================================

CREATE POLICY "Members can view runs" ON customer_runs
    FOR SELECT USING (
        project_id IS NULL OR has_project_access(project_id, auth.uid())
    );

CREATE POLICY "Members can create runs" ON customer_runs
    FOR INSERT WITH CHECK (
        project_id IS NULL OR has_project_access(project_id, auth.uid())
    );

-- ============================================================================
-- TEST SESSIONS POLICIES
-- ============================================================================

CREATE POLICY "Members can view test sessions" ON test_sessions
    FOR SELECT USING (
        project_id IS NULL OR has_project_access(project_id, auth.uid())
    );

CREATE POLICY "Editors can create test sessions" ON test_sessions
    FOR INSERT WITH CHECK (
        project_id IS NULL OR can_edit_project(project_id, auth.uid())
    );

CREATE POLICY "Editors can update test sessions" ON test_sessions
    FOR UPDATE USING (
        project_id IS NULL OR can_edit_project(project_id, auth.uid())
    );

-- ============================================================================
-- TEST RESULTS POLICIES
-- ============================================================================

CREATE POLICY "Members can view test results" ON test_results
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM test_sessions ts
            WHERE ts.session_id = test_results.session_id
            AND (ts.project_id IS NULL OR has_project_access(ts.project_id, auth.uid()))
        )
    );

CREATE POLICY "System can insert test results" ON test_results
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM test_sessions ts
            WHERE ts.session_id = test_results.session_id
            AND (ts.project_id IS NULL OR can_edit_project(ts.project_id, auth.uid()))
        )
    );

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Auto-add owner as project member when project is created
CREATE OR REPLACE FUNCTION add_owner_as_member()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO project_members (project_id, user_id, role, invited_by)
    VALUES (NEW.id, NEW.owner_id, 'owner', NEW.owner_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trigger_add_owner_as_member ON projects;
CREATE TRIGGER trigger_add_owner_as_member
    AFTER INSERT ON projects
    FOR EACH ROW
    EXECUTE FUNCTION add_owner_as_member();

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_projects_updated_at ON projects;
CREATE TRIGGER trigger_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trigger_project_data_updated_at ON project_data;
CREATE TRIGGER trigger_project_data_updated_at
    BEFORE UPDATE ON project_data
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- INVITATION ACCEPTANCE FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION accept_invitation(p_token VARCHAR)
RETURNS JSONB AS $$
DECLARE
    v_invitation project_invitations%ROWTYPE;
    v_user_id UUID;
BEGIN
    v_user_id := auth.uid();

    IF v_user_id IS NULL THEN
        RETURN jsonb_build_object('success', false, 'error', 'Not authenticated');
    END IF;

    -- Get invitation
    SELECT * INTO v_invitation
    FROM project_invitations
    WHERE token = p_token AND status = 'pending' AND expires_at > NOW();

    IF v_invitation.id IS NULL THEN
        RETURN jsonb_build_object('success', false, 'error', 'Invalid or expired invitation');
    END IF;

    -- Check if email matches
    IF v_invitation.email != (SELECT email FROM auth.users WHERE id = v_user_id) THEN
        RETURN jsonb_build_object('success', false, 'error', 'Invitation is for a different email');
    END IF;

    -- Add user to project
    INSERT INTO project_members (project_id, user_id, role, invited_by)
    VALUES (v_invitation.project_id, v_user_id, v_invitation.role, v_invitation.invited_by)
    ON CONFLICT (project_id, user_id) DO NOTHING;

    -- Update invitation status
    UPDATE project_invitations SET status = 'accepted' WHERE id = v_invitation.id;

    RETURN jsonb_build_object('success', true, 'project_id', v_invitation.project_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
