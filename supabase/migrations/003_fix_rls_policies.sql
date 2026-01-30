-- ============================================================================
-- Fix RLS Policies for Project Creation
-- ============================================================================

-- Drop existing policies on projects table
DROP POLICY IF EXISTS "Users can view their projects" ON projects;
DROP POLICY IF EXISTS "Users can create projects" ON projects;
DROP POLICY IF EXISTS "Owners can update projects" ON projects;
DROP POLICY IF EXISTS "Owners can delete projects" ON projects;

-- Recreate policies with proper permissions

-- Anyone authenticated can create a project (they become the owner)
CREATE POLICY "Authenticated users can create projects" ON projects
    FOR INSERT
    TO authenticated
    WITH CHECK (owner_id = auth.uid());

-- Users can view projects they own OR are members of
CREATE POLICY "Users can view accessible projects" ON projects
    FOR SELECT
    TO authenticated
    USING (
        owner_id = auth.uid()
        OR EXISTS (
            SELECT 1 FROM project_members
            WHERE project_members.project_id = projects.id
            AND project_members.user_id = auth.uid()
        )
    );

-- Only owners can update their projects
CREATE POLICY "Owners can update their projects" ON projects
    FOR UPDATE
    TO authenticated
    USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

-- Only owners can delete their projects
CREATE POLICY "Owners can delete their projects" ON projects
    FOR DELETE
    TO authenticated
    USING (owner_id = auth.uid());

-- ============================================================================
-- Fix Project Members Policies
-- ============================================================================

DROP POLICY IF EXISTS "Members can view project members" ON project_members;
DROP POLICY IF EXISTS "Owners can manage members" ON project_members;
DROP POLICY IF EXISTS "Owners can update members" ON project_members;
DROP POLICY IF EXISTS "Owners can remove members" ON project_members;

-- System trigger inserts (for owner auto-add)
CREATE POLICY "System can insert members" ON project_members
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Members can view other members in their projects
CREATE POLICY "Members can view project members" ON project_members
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_members.project_id
            AND pm.user_id = auth.uid()
        )
    );

-- Owners can update member roles
CREATE POLICY "Owners can update members" ON project_members
    FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_members.project_id
            AND pm.user_id = auth.uid()
            AND pm.role = 'owner'
        )
    );

-- Owners can remove members
CREATE POLICY "Owners can remove members" ON project_members
    FOR DELETE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_members.project_id
            AND pm.user_id = auth.uid()
            AND pm.role = 'owner'
        )
        AND user_id != auth.uid()  -- Can't remove self
    );

-- ============================================================================
-- Fix Project Invitations Policies
-- ============================================================================

DROP POLICY IF EXISTS "Owners can view invitations" ON project_invitations;
DROP POLICY IF EXISTS "Owners can create invitations" ON project_invitations;
DROP POLICY IF EXISTS "Owners can update invitations" ON project_invitations;

-- Owners can manage invitations
CREATE POLICY "Owners can manage invitations" ON project_invitations
    FOR ALL
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_invitations.project_id
            AND pm.user_id = auth.uid()
            AND pm.role = 'owner'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_invitations.project_id
            AND pm.user_id = auth.uid()
            AND pm.role = 'owner'
        )
    );

-- Users can view invitations sent to them
CREATE POLICY "Users can view their invitations" ON project_invitations
    FOR SELECT
    TO authenticated
    USING (
        email = (SELECT email FROM auth.users WHERE id = auth.uid())
    );

-- ============================================================================
-- Fix Project Data Policies
-- ============================================================================

DROP POLICY IF EXISTS "Members can view project data" ON project_data;
DROP POLICY IF EXISTS "Editors can upload data" ON project_data;
DROP POLICY IF EXISTS "Editors can update data" ON project_data;
DROP POLICY IF EXISTS "Editors can delete data" ON project_data;

-- Members can view project data
CREATE POLICY "Members can view project data" ON project_data
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_data.project_id
            AND pm.user_id = auth.uid()
        )
    );

-- Editors and owners can manage data
CREATE POLICY "Editors can manage data" ON project_data
    FOR ALL
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_data.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = project_data.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    );

-- ============================================================================
-- Fix Prompts Policies
-- ============================================================================

DROP POLICY IF EXISTS "Members can view system prompts" ON system_prompts;
DROP POLICY IF EXISTS "Editors can create system prompts" ON system_prompts;
DROP POLICY IF EXISTS "Editors can update system prompts" ON system_prompts;
DROP POLICY IF EXISTS "Members can view user prompts" ON user_prompts;
DROP POLICY IF EXISTS "Editors can create user prompts" ON user_prompts;
DROP POLICY IF EXISTS "Editors can update user prompts" ON user_prompts;

-- System prompts policies
CREATE POLICY "View system prompts" ON system_prompts
    FOR SELECT
    TO authenticated
    USING (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = system_prompts.project_id
            AND pm.user_id = auth.uid()
        )
    );

CREATE POLICY "Manage system prompts" ON system_prompts
    FOR ALL
    TO authenticated
    USING (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = system_prompts.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    )
    WITH CHECK (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = system_prompts.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    );

-- User prompts policies
CREATE POLICY "View user prompts" ON user_prompts
    FOR SELECT
    TO authenticated
    USING (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = user_prompts.project_id
            AND pm.user_id = auth.uid()
        )
    );

CREATE POLICY "Manage user prompts" ON user_prompts
    FOR ALL
    TO authenticated
    USING (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = user_prompts.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    )
    WITH CHECK (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = user_prompts.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    );

-- ============================================================================
-- Fix Test Sessions Policies
-- ============================================================================

DROP POLICY IF EXISTS "Members can view test sessions" ON test_sessions;
DROP POLICY IF EXISTS "Editors can create test sessions" ON test_sessions;
DROP POLICY IF EXISTS "Editors can update test sessions" ON test_sessions;

CREATE POLICY "View test sessions" ON test_sessions
    FOR SELECT
    TO authenticated
    USING (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = test_sessions.project_id
            AND pm.user_id = auth.uid()
        )
    );

CREATE POLICY "Manage test sessions" ON test_sessions
    FOR ALL
    TO authenticated
    USING (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = test_sessions.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    )
    WITH CHECK (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = test_sessions.project_id
            AND pm.user_id = auth.uid()
            AND pm.role IN ('owner', 'editor')
        )
    );

-- ============================================================================
-- Fix Test Results Policies
-- ============================================================================

DROP POLICY IF EXISTS "Members can view test results" ON test_results;
DROP POLICY IF EXISTS "System can insert test results" ON test_results;

CREATE POLICY "View test results" ON test_results
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM test_sessions ts
            WHERE ts.session_id = test_results.session_id
            AND (
                ts.project_id IS NULL
                OR EXISTS (
                    SELECT 1 FROM project_members pm
                    WHERE pm.project_id = ts.project_id
                    AND pm.user_id = auth.uid()
                )
            )
        )
    );

CREATE POLICY "Insert test results" ON test_results
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM test_sessions ts
            WHERE ts.session_id = test_results.session_id
            AND (
                ts.project_id IS NULL
                OR EXISTS (
                    SELECT 1 FROM project_members pm
                    WHERE pm.project_id = ts.project_id
                    AND pm.user_id = auth.uid()
                    AND pm.role IN ('owner', 'editor')
                )
            )
        )
    );

-- ============================================================================
-- Fix Customer Runs Policies
-- ============================================================================

DROP POLICY IF EXISTS "Members can view runs" ON customer_runs;
DROP POLICY IF EXISTS "Members can create runs" ON customer_runs;

CREATE POLICY "View customer runs" ON customer_runs
    FOR SELECT
    TO authenticated
    USING (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = customer_runs.project_id
            AND pm.user_id = auth.uid()
        )
    );

CREATE POLICY "Create customer runs" ON customer_runs
    FOR INSERT
    TO authenticated
    WITH CHECK (
        project_id IS NULL
        OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = customer_runs.project_id
            AND pm.user_id = auth.uid()
        )
    );
