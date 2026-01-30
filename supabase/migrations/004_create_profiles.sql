-- ============================================================================
-- Create Profiles Table (mirrors auth.users for public access)
-- ============================================================================

CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email VARCHAR(255),
    full_name VARCHAR(255),
    avatar_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- Everyone can view profiles
CREATE POLICY "Profiles are viewable by everyone" ON profiles
    FOR SELECT TO authenticated USING (true);

-- Users can update their own profile
CREATE POLICY "Users can update own profile" ON profiles
    FOR UPDATE TO authenticated USING (id = auth.uid());

-- Users can insert their own profile
CREATE POLICY "Users can insert own profile" ON profiles
    FOR INSERT TO authenticated WITH CHECK (id = auth.uid());

-- ============================================================================
-- Function to handle new user signup
-- ============================================================================

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name, avatar_url)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', ''),
        COALESCE(NEW.raw_user_meta_data->>'avatar_url', NEW.raw_user_meta_data->>'picture', '')
    )
    ON CONFLICT (id) DO UPDATE SET
        email = EXCLUDED.email,
        full_name = EXCLUDED.full_name,
        avatar_url = EXCLUDED.avatar_url,
        updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger on auth.users
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT OR UPDATE ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user();

-- ============================================================================
-- Backfill existing users
-- ============================================================================

INSERT INTO profiles (id, email, full_name, avatar_url)
SELECT
    id,
    email,
    COALESCE(raw_user_meta_data->>'full_name', raw_user_meta_data->>'name', ''),
    COALESCE(raw_user_meta_data->>'avatar_url', raw_user_meta_data->>'picture', '')
FROM auth.users
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    full_name = EXCLUDED.full_name,
    avatar_url = EXCLUDED.avatar_url;

-- ============================================================================
-- Update project_members to store email directly for easier access
-- ============================================================================

ALTER TABLE project_members ADD COLUMN IF NOT EXISTS user_email VARCHAR(255);
ALTER TABLE project_members ADD COLUMN IF NOT EXISTS user_name VARCHAR(255);

-- Update existing members with profile info
UPDATE project_members pm
SET
    user_email = p.email,
    user_name = p.full_name
FROM profiles p
WHERE pm.user_id = p.id AND pm.user_email IS NULL;

-- ============================================================================
-- Update the add_owner_as_member trigger to include user info
-- ============================================================================

CREATE OR REPLACE FUNCTION add_owner_as_member()
RETURNS TRIGGER AS $$
DECLARE
    v_email VARCHAR(255);
    v_name VARCHAR(255);
BEGIN
    -- Get user info from profiles
    SELECT email, full_name INTO v_email, v_name
    FROM profiles WHERE id = NEW.owner_id;

    INSERT INTO project_members (project_id, user_id, role, invited_by, user_email, user_name)
    VALUES (NEW.id, NEW.owner_id, 'owner', NEW.owner_id, v_email, v_name);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
