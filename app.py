"""
PromptHist - Prompt Testing & History Platform
"""

import os
import re
import glob
import json
import time
import uuid
import secrets
import smtplib
import requests
import numpy as np
import pandas as pd
from io import StringIO, BytesIO
from datetime import datetime
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, g
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_PATH, "data")
PROMPTS_PATH = os.path.join(BASE_PATH, "prompts")
RUNS_PATH = os.path.join(BASE_PATH, "runs")
SESSIONS_PATH = os.path.join(BASE_PATH, "sessions")
UPLOADS_PATH = os.path.join(BASE_PATH, "uploads")

# Email configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USER)
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "PromptHist")

# Supabase client
SUPABASE_URL = os.getenv("SUPABASE_PROJECT_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
supabase = None

try:
    from supabase import create_client, Client
    if SUPABASE_URL and SUPABASE_KEY:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase client initialized successfully")
except ImportError:
    print("Supabase package not installed, using file-based storage only")
except Exception as e:
    print(f"Supabase initialization error: {e}")

# Ensure directories exist
os.makedirs(RUNS_PATH, exist_ok=True)
os.makedirs(SESSIONS_PATH, exist_ok=True)
os.makedirs(UPLOADS_PATH, exist_ok=True)

# =============================================================================
# AUTHENTICATION HELPERS
# =============================================================================

def get_user_from_token():
    """Extract user from Authorization header"""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None

    token = auth_header[7:]
    if not token or not supabase:
        return None

    try:
        # Verify token with Supabase
        user_response = supabase.auth.get_user(token)
        if user_response and user_response.user:
            return {
                'id': user_response.user.id,
                'email': user_response.user.email,
                'name': user_response.user.user_metadata.get('full_name', user_response.user.email)
            }
    except Exception as e:
        print(f"Token verification error: {e}")

    return None

def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_user_from_token()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated_function

def get_user_client():
    """Get a Supabase client with user's token for RLS"""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return supabase

    token = auth_header[7:]
    if not token:
        return supabase

    try:
        from supabase import create_client
        from supabase.lib.client_options import ClientOptions

        # Create client with user's access token in headers
        options = ClientOptions(
            headers={"Authorization": f"Bearer {token}"}
        )
        client = create_client(SUPABASE_URL, SUPABASE_KEY, options)
        return client
    except Exception as e:
        print(f"User client creation error: {e}")
        return supabase

# =============================================================================
# PROJECT MANAGEMENT
# =============================================================================

@app.route('/api/projects', methods=['GET'])
@require_auth
def get_projects():
    """Get all projects for the current user"""
    try:
        client = get_user_client()
        result = client.table('project_members').select(
            'role, projects(*)'
        ).eq('user_id', g.user['id']).execute()

        projects = []
        project_ids = []
        for pm in result.data:
            if pm['projects']:
                project = pm['projects']
                project['role'] = pm['role']
                projects.append(project)
                project_ids.append(project['id'])

        # Get data counts for all projects
        if project_ids:
            data_result = client.table('project_data').select(
                'project_id'
            ).in_('project_id', project_ids).execute()

            # Count data per project
            data_counts = {}
            for d in data_result.data:
                pid = d['project_id']
                data_counts[pid] = data_counts.get(pid, 0) + 1

            # Add hasData flag to each project
            for project in projects:
                project['hasData'] = data_counts.get(project['id'], 0) > 0

        return jsonify({'projects': projects})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects', methods=['POST'])
@require_auth
def create_project():
    """Create a new project"""
    try:
        name = request.json.get('name')
        description = request.json.get('description', '')

        if not name:
            return jsonify({'error': 'Project name is required'}), 400

        client = get_user_client()
        result = client.table('projects').insert({
            'name': name,
            'description': description,
            'owner_id': g.user['id']
        }).execute()

        if result.data:
            return jsonify({'project': result.data[0]})
        return jsonify({'error': 'Failed to create project'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>', methods=['GET'])
@require_auth
def get_project(project_id):
    """Get a single project with details"""
    try:
        client = get_user_client()

        # Get project
        result = client.table('projects').select('*').eq('id', project_id).single().execute()
        if not result.data:
            return jsonify({'error': 'Project not found'}), 404

        project = result.data

        # Get members
        members_result = client.table('project_members').select(
            '*, user:user_id(email)'
        ).eq('project_id', project_id).execute()
        project['members'] = members_result.data

        # Get user's role
        for member in members_result.data:
            if member['user_id'] == g.user['id']:
                project['current_user_role'] = member['role']
                break

        return jsonify({'project': project})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>', methods=['PUT'])
@require_auth
def update_project(project_id):
    """Update a project"""
    try:
        client = get_user_client()

        updates = {}
        if 'name' in request.json:
            updates['name'] = request.json['name']
        if 'description' in request.json:
            updates['description'] = request.json['description']
        if 'settings' in request.json:
            updates['settings'] = request.json['settings']

        result = client.table('projects').update(updates).eq('id', project_id).execute()

        if result.data:
            return jsonify({'project': result.data[0]})
        return jsonify({'error': 'Failed to update project'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>', methods=['DELETE'])
@require_auth
def delete_project(project_id):
    """Delete a project"""
    try:
        client = get_user_client()
        client.table('projects').delete().eq('id', project_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# PROJECT MEMBERS
# =============================================================================

@app.route('/api/projects/<project_id>/members', methods=['GET'])
@require_auth
def get_project_members(project_id):
    """Get all members of a project"""
    try:
        client = get_user_client()
        # Get members with profile info
        result = client.table('project_members').select(
            '*, profiles(email, full_name, avatar_url)'
        ).eq('project_id', project_id).execute()

        # Format response with user info
        members = []
        for m in result.data:
            profile = m.get('profiles') or {}
            members.append({
                'id': m['id'],
                'user_id': m['user_id'],
                'role': m['role'],
                'email': m.get('user_email') or profile.get('email') or 'Unknown',
                'name': m.get('user_name') or profile.get('full_name') or '',
                'avatar_url': profile.get('avatar_url') or ''
            })

        return jsonify({'members': members})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/members', methods=['POST'])
@require_auth
def add_project_member(project_id):
    """Add a member to a project (direct add if user exists)"""
    try:
        user_id = request.json.get('user_id')
        role = request.json.get('role', 'viewer')

        if role not in ['editor', 'viewer']:
            return jsonify({'error': 'Invalid role'}), 400

        client = get_user_client()
        result = client.table('project_members').insert({
            'project_id': project_id,
            'user_id': user_id,
            'role': role,
            'invited_by': g.user['id']
        }).execute()

        if result.data:
            return jsonify({'member': result.data[0]})
        return jsonify({'error': 'Failed to add member'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/members/<user_id>', methods=['PUT'])
@require_auth
def update_project_member(project_id, user_id):
    """Update a member's role"""
    try:
        role = request.json.get('role')
        if role not in ['editor', 'viewer']:
            return jsonify({'error': 'Invalid role'}), 400

        client = get_user_client()
        result = client.table('project_members').update({
            'role': role
        }).eq('project_id', project_id).eq('user_id', user_id).execute()

        if result.data:
            return jsonify({'member': result.data[0]})
        return jsonify({'error': 'Failed to update member'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/members/<user_id>', methods=['DELETE'])
@require_auth
def remove_project_member(project_id, user_id):
    """Remove a member from a project"""
    try:
        client = get_user_client()
        client.table('project_members').delete().eq('project_id', project_id).eq('user_id', user_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# PROJECT INVITATIONS
# =============================================================================

@app.route('/api/projects/<project_id>/invitations', methods=['GET'])
@require_auth
def get_project_invitations(project_id):
    """Get all invitations for a project"""
    try:
        client = get_user_client()
        result = client.table('project_invitations').select('*').eq(
            'project_id', project_id
        ).order('created_at', desc=True).execute()

        # Add invitation links
        invitations = []
        for inv in result.data:
            inv['link'] = f"{request.host_url}app?invite={inv['token']}"
            invitations.append(inv)

        return jsonify({'invitations': invitations})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/invitations', methods=['POST'])
@require_auth
def create_invitation(project_id):
    """Create an invitation to join a project"""
    try:
        email = request.json.get('email')
        role = request.json.get('role', 'viewer')

        if not email:
            return jsonify({'error': 'Email is required'}), 400
        if role not in ['editor', 'viewer']:
            return jsonify({'error': 'Invalid role'}), 400

        token = secrets.token_urlsafe(32)

        client = get_user_client()

        # Check if invitation already exists
        existing = client.table('project_invitations').select('id').eq(
            'project_id', project_id
        ).eq('email', email).eq('status', 'pending').execute()

        if existing.data:
            return jsonify({'error': 'An invitation for this email already exists'}), 400

        # Get project name for email
        project_result = client.table('projects').select('name').eq('id', project_id).single().execute()
        project_name = project_result.data['name'] if project_result.data else 'Unknown Project'

        result = client.table('project_invitations').insert({
            'project_id': project_id,
            'email': email,
            'role': role,
            'invited_by': g.user['id'],
            'token': token
        }).execute()

        if result.data:
            invitation = result.data[0]
            invitation['link'] = f"{request.host_url}app?invite={token}"

            # Send invitation email
            try:
                email_sent = send_invitation_email(email, invitation['link'], project_name, g.user['name'], role)
                invitation['email_sent'] = email_sent
                invitation['email_configured'] = bool(SMTP_USER and SMTP_PASSWORD)
            except Exception as e:
                print(f"Email send error: {e}")
                invitation['email_sent'] = False
                invitation['email_error'] = str(e)

            return jsonify({'invitation': invitation})
        return jsonify({'error': 'Failed to create invitation'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def send_invitation_email(to_email, invite_link, project_name, inviter_name, role):
    """Send invitation email using SMTP"""
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL] SMTP not configured. Would send invitation to {to_email}")
        print(f"[EMAIL] Link: {invite_link}")
        return False

    # Create HTML email
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 12px 12px 0 0; text-align: center; }}
            .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 12px 12px; }}
            .button {{ display: inline-block; background: #667eea; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 20px 0; }}
            .button:hover {{ background: #5a67d8; }}
            .role-badge {{ display: inline-block; background: #e0e7ff; color: #4338ca; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: 500; }}
            .footer {{ text-align: center; color: #6b7280; font-size: 12px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0;">You're Invited!</h1>
            </div>
            <div class="content">
                <p>Hi there,</p>
                <p><strong>{inviter_name}</strong> has invited you to join the project <strong>"{project_name}"</strong> on PromptHist.</p>
                <p>Your role: <span class="role-badge">{role.capitalize()}</span></p>
                <p style="text-align: center;">
                    <a href="{invite_link}" class="button">Accept Invitation</a>
                </p>
                <p style="color: #6b7280; font-size: 14px;">Or copy this link: <br><a href="{invite_link}" style="color: #667eea; word-break: break-all;">{invite_link}</a></p>
            </div>
            <div class="footer">
                <p>This invitation was sent from PromptHist. If you didn't expect this email, you can safely ignore it.</p>
            </div>
        </div>
    </body>
    </html>
    """

    # Plain text fallback
    text_content = f"""
You're Invited to {project_name}!

{inviter_name} has invited you to join the project "{project_name}" on PromptHist.

Your role: {role.capitalize()}

Click here to accept: {invite_link}

If you didn't expect this email, you can safely ignore it.
    """

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"You're invited to join {project_name}"
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email

        # Attach both plain text and HTML versions
        msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

        # Send email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())

        print(f"[EMAIL] Invitation sent to {to_email}")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed to send to {to_email}: {e}")
        raise e

@app.route('/api/projects/<project_id>/invitations/<invitation_id>/resend', methods=['POST'])
@require_auth
def resend_invitation(project_id, invitation_id):
    """Resend an invitation"""
    try:
        client = get_user_client()

        # Get invitation
        inv_result = client.table('project_invitations').select('*').eq(
            'id', invitation_id
        ).eq('project_id', project_id).single().execute()

        if not inv_result.data:
            return jsonify({'error': 'Invitation not found'}), 404

        invitation = inv_result.data

        # Generate new token and reset expiry
        new_token = secrets.token_urlsafe(32)
        client.table('project_invitations').update({
            'token': new_token,
            'status': 'pending',
            'expires_at': (datetime.now() + pd.Timedelta(days=7)).isoformat()
        }).eq('id', invitation_id).execute()

        # Get project name
        project_result = client.table('projects').select('name').eq('id', project_id).single().execute()
        project_name = project_result.data['name'] if project_result.data else 'Unknown Project'

        invite_link = f"{request.host_url}app?invite={new_token}"

        # Send email
        email_sent = False
        email_error = None
        try:
            email_sent = send_invitation_email(invitation['email'], invite_link, project_name, g.user['name'], invitation['role'])
        except Exception as e:
            email_error = str(e)

        return jsonify({
            'success': True,
            'link': invite_link,
            'email_sent': email_sent,
            'email_configured': bool(SMTP_USER and SMTP_PASSWORD),
            'email_error': email_error
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/my-invitations', methods=['GET'])
@require_auth
def get_my_invitations():
    """Get pending invitations for the current user"""
    try:
        client = get_user_client()
        user_email = g.user['email']

        # Get pending invitations for this user's email
        result = client.table('project_invitations').select(
            '*, projects(id, name, description)'
        ).eq('email', user_email).eq('status', 'pending').execute()

        invitations = []
        for inv in result.data or []:
            project = inv.get('projects', {})
            invitations.append({
                'id': inv['id'],
                'token': inv['token'],
                'role': inv['role'],
                'created_at': inv['created_at'],
                'project_id': inv['project_id'],
                'project_name': project.get('name', 'Unknown Project'),
                'project_description': project.get('description', '')
            })

        return jsonify({'invitations': invitations})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/invitations/accept', methods=['POST'])
@require_auth
def accept_invitation():
    """Accept an invitation"""
    try:
        token = request.json.get('token')
        if not token:
            return jsonify({'error': 'Token is required'}), 400

        client = get_user_client()

        # Get invitation
        inv_result = client.table('project_invitations').select('*').eq(
            'token', token
        ).eq('status', 'pending').single().execute()

        if not inv_result.data:
            return jsonify({'error': 'Invalid or expired invitation'}), 404

        invitation = inv_result.data

        # Check if email matches
        if invitation['email'].lower() != g.user['email'].lower():
            return jsonify({'error': 'This invitation is for a different email'}), 403

        # Add member with user info
        client.table('project_members').insert({
            'project_id': invitation['project_id'],
            'user_id': g.user['id'],
            'role': invitation['role'],
            'invited_by': invitation['invited_by'],
            'user_email': g.user['email'],
            'user_name': g.user['name']
        }).execute()

        # Update invitation status
        client.table('project_invitations').update({
            'status': 'accepted'
        }).eq('id', invitation['id']).execute()

        return jsonify({'success': True, 'project_id': invitation['project_id']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/invitations/reject', methods=['POST'])
@require_auth
def reject_invitation():
    """Reject an invitation"""
    try:
        token = request.json.get('token')
        if not token:
            return jsonify({'error': 'Token is required'}), 400

        client = get_user_client()

        # Get invitation
        inv_result = client.table('project_invitations').select('*').eq(
            'token', token
        ).eq('status', 'pending').single().execute()

        if not inv_result.data:
            return jsonify({'error': 'Invalid or expired invitation'}), 404

        invitation = inv_result.data

        # Check if email matches
        if invitation['email'].lower() != g.user['email'].lower():
            return jsonify({'error': 'This invitation is for a different email'}), 403

        # Update invitation status to cancelled (declined by user)
        client.table('project_invitations').update({
            'status': 'cancelled'
        }).eq('id', invitation['id']).execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/invitations/<invitation_id>', methods=['DELETE'])
@require_auth
def cancel_invitation(project_id, invitation_id):
    """Cancel/revoke an invitation"""
    try:
        client = get_user_client()
        client.table('project_invitations').update({
            'status': 'cancelled'
        }).eq('id', invitation_id).eq('project_id', project_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/bind-existing-data', methods=['POST'])
@require_auth
def bind_existing_data(project_id):
    """Bind all unassigned prompts, test sessions, and runs to a project"""
    try:
        client = get_user_client()

        # Update system_prompts
        client.table('system_prompts').update({'project_id': project_id}).is_('project_id', 'null').execute()

        # Update user_prompts
        client.table('user_prompts').update({'project_id': project_id}).is_('project_id', 'null').execute()

        # Update test_sessions
        client.table('test_sessions').update({'project_id': project_id}).is_('project_id', 'null').execute()

        # Update customer_runs
        client.table('customer_runs').update({'project_id': project_id}).is_('project_id', 'null').execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/transfer-ownership', methods=['POST'])
@require_auth
def transfer_ownership(project_id):
    """Transfer project ownership to another member"""
    try:
        new_owner_id = request.json.get('user_id')
        if not new_owner_id:
            return jsonify({'error': 'User ID is required'}), 400

        client = get_user_client()

        # Verify current user is the owner
        current_member = client.table('project_members').select('role').eq(
            'project_id', project_id
        ).eq('user_id', g.user['id']).single().execute()

        if not current_member.data or current_member.data['role'] != 'owner':
            return jsonify({'error': 'Only the owner can transfer ownership'}), 403

        # Update project owner
        client.table('projects').update({
            'owner_id': new_owner_id
        }).eq('id', project_id).execute()

        # Update member roles: new owner becomes owner, old owner becomes editor
        client.table('project_members').update({
            'role': 'owner'
        }).eq('project_id', project_id).eq('user_id', new_owner_id).execute()

        client.table('project_members').update({
            'role': 'editor'
        }).eq('project_id', project_id).eq('user_id', g.user['id']).execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# PROJECT DATA MANAGEMENT
# =============================================================================

@app.route('/api/projects/<project_id>/data', methods=['GET'])
@require_auth
def get_project_data(project_id):
    """Get all data files for a project"""
    try:
        client = get_user_client()
        result = client.table('project_data').select('*').eq(
            'project_id', project_id
        ).order('created_at', desc=True).execute()
        return jsonify({'data': result.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/data', methods=['POST'])
@require_auth
def upload_project_data(project_id):
    """Upload data to a project and import rows into database"""
    try:
        name = request.form.get('name')
        description = request.form.get('description', '')
        file = request.files.get('file')

        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if not file:
            return jsonify({'error': 'File is required'}), 400

        # Determine file type
        filename = file.filename.lower()
        if filename.endswith('.csv'):
            file_type = 'csv'
        elif filename.endswith('.json'):
            file_type = 'json'
        elif filename.endswith(('.xlsx', '.xls')):
            file_type = 'excel'
        else:
            file_type = 'text'

        # Read and process file
        content = file.read()
        rows_data = []
        column_info = []

        try:
            if file_type == 'csv':
                import csv
                text_content = content.decode('utf-8')

                # Read first 10 lines to detect CSV dialect
                sample_lines = '\n'.join(text_content.split('\n')[:10])

                # Use csv.Sniffer to detect delimiter and quote character
                try:
                    sniffer = csv.Sniffer()
                    dialect = sniffer.sniff(sample_lines)
                    delimiter = dialect.delimiter
                    quotechar = dialect.quotechar
                    print(f"Detected CSV: delimiter='{delimiter}', quotechar='{quotechar}'")
                except Exception as sniff_error:
                    print(f"Sniffer failed: {sniff_error}, using defaults")
                    delimiter = ','
                    quotechar = '"'

                # Parse CSV with detected parameters
                try:
                    df = pd.read_csv(
                        StringIO(text_content),
                        sep=delimiter,
                        quotechar=quotechar,
                        on_bad_lines='skip',
                        engine='python'
                    )
                except Exception as parse_error:
                    print(f"First parse attempt failed: {parse_error}")
                    # Fallback: try with more flexible options
                    df = pd.read_csv(
                        StringIO(text_content),
                        sep=delimiter,
                        quotechar=quotechar,
                        on_bad_lines='skip',
                        engine='python',
                        encoding_errors='ignore'
                    )

                column_info = [{'name': col, 'type': str(df[col].dtype)} for col in df.columns]
                rows_data = df.to_dict('records')
                print(f"Parsed {len(rows_data)} rows with {len(column_info)} columns")

            elif file_type == 'json':
                data = json.loads(content.decode('utf-8'))
                if isinstance(data, list):
                    rows_data = data
                    if data:
                        column_info = [{'name': k, 'type': type(v).__name__} for k, v in data[0].items()]
            elif file_type == 'excel':
                df = pd.read_excel(BytesIO(content))
                column_info = [{'name': col, 'type': str(df[col].dtype)} for col in df.columns]
                rows_data = df.to_dict('records')
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'File parsing error: {str(e)}'}), 400

        if not rows_data:
            return jsonify({'error': 'No data rows found in file'}), 400

        # Generate upload instance ID
        upload_instance_id = str(uuid.uuid4())

        # Save file to storage (backup)
        file_path = os.path.join(UPLOADS_PATH, project_id)
        os.makedirs(file_path, exist_ok=True)
        full_path = os.path.join(file_path, f"{upload_instance_id}.{file_type}")

        with open(full_path, 'wb') as f:
            f.write(content)

        client = get_user_client()

        # Save upload metadata to database
        upload_result = client.table('project_data').insert({
            'project_id': project_id,
            'upload_instance_id': upload_instance_id,
            'name': name,
            'description': description,
            'file_type': file_type,
            'file_path': full_path,
            'row_count': len(rows_data),
            'column_info': column_info,
            'uploaded_by': g.user['id']
        }).execute()

        if not upload_result.data:
            return jsonify({'error': 'Failed to save upload metadata'}), 500

        # Find identifier column
        id_col = None
        for col in ['CUSTOMER_NUM', 'customer_num', 'Customer_Num', 'id', 'ID', 'Id', 'name', 'Name']:
            if col in rows_data[0]:
                id_col = col
                break

        # Import each row into database
        rows_to_insert = []
        for idx, row in enumerate(rows_data):
            # Convert any NaN values to None and handle data types
            cleaned_row = {}
            for k, v in row.items():
                if pd.isna(v):
                    cleaned_row[k] = None
                elif isinstance(v, (np.integer, np.floating)):
                    cleaned_row[k] = v.item()
                else:
                    cleaned_row[k] = v

            identifier = str(cleaned_row.get(id_col, idx)) if id_col else str(idx)

            # Format row data as text
            data_text = '\n'.join([f"{k}: {v}" for k, v in cleaned_row.items() if v is not None])

            rows_to_insert.append({
                'project_id': project_id,
                'upload_instance_id': upload_instance_id,
                'row_index': idx,
                'identifier': identifier,
                'row_data': cleaned_row,
                'data_text': data_text
            })

        # Batch insert rows (Supabase has limits, so chunk if needed)
        chunk_size = 500
        for i in range(0, len(rows_to_insert), chunk_size):
            chunk = rows_to_insert[i:i + chunk_size]
            client.table('project_data_rows').insert(chunk).execute()

        return jsonify({
            'data': upload_result.data[0],
            'rows_imported': len(rows_to_insert)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/rows', methods=['GET'])
@require_auth
def get_project_rows(project_id):
    """Get all data rows for a project (for Preview dropdown)"""
    try:
        client = get_user_client()
        result = client.table('project_data_rows').select(
            'id, identifier, upload_instance_id'
        ).eq('project_id', project_id).order('identifier').execute()

        return jsonify({'rows': result.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/rows/<row_id>', methods=['GET'])
@require_auth
def get_project_row(project_id, row_id):
    """Get a specific data row for preview"""
    try:
        client = get_user_client()
        result = client.table('project_data_rows').select('*').eq(
            'id', row_id
        ).eq('project_id', project_id).single().execute()

        if not result.data:
            return jsonify({'error': 'Row not found'}), 404

        return jsonify({
            'row': result.data,
            'data_text': result.data.get('data_text', ''),
            'identifier': result.data.get('identifier', '')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/data/<data_id>', methods=['GET'])
@require_auth
def get_project_data_details(project_id, data_id):
    """Get details of a data file including content"""
    try:
        client = get_user_client()
        result = client.table('project_data').select('*').eq(
            'id', data_id
        ).eq('project_id', project_id).single().execute()

        if not result.data:
            return jsonify({'error': 'Data not found'}), 404

        data = result.data

        # Load file content if needed
        if request.args.get('include_content') == 'true':
            try:
                with open(data['file_path'], 'r', encoding='utf-8') as f:
                    if data['file_type'] == 'csv':
                        df = pd.read_csv(f)
                        data['content'] = df.to_dict('records')
                    elif data['file_type'] == 'json':
                        data['content'] = json.load(f)
                    else:
                        data['content'] = f.read()
            except Exception as e:
                data['content_error'] = str(e)

        return jsonify({'data': data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/data/<data_id>/rows', methods=['GET'])
@require_auth
def get_project_data_rows(project_id, data_id):
    """Get all rows from a data file for preview selection"""
    try:
        client = get_user_client()
        result = client.table('project_data').select('*').eq(
            'id', data_id
        ).eq('project_id', project_id).single().execute()

        if not result.data:
            return jsonify({'error': 'Data not found'}), 404

        data = result.data
        rows = []

        try:
            with open(data['file_path'], 'r', encoding='utf-8') as f:
                if data['file_type'] == 'csv':
                    df = pd.read_csv(f)
                    # Try to find an identifier column
                    id_col = None
                    for col in ['CUSTOMER_NUM', 'customer_num', 'id', 'ID', 'name', 'Name']:
                        if col in df.columns:
                            id_col = col
                            break
                    if not id_col and len(df.columns) > 0:
                        id_col = df.columns[0]

                    for idx, row in df.iterrows():
                        rows.append({
                            'index': idx,
                            'identifier': str(row[id_col]) if id_col else str(idx),
                            'data': row.to_dict()
                        })
                elif data['file_type'] == 'json':
                    content = json.load(f)
                    if isinstance(content, list):
                        for idx, item in enumerate(content):
                            identifier = item.get('CUSTOMER_NUM') or item.get('id') or item.get('name') or str(idx)
                            rows.append({
                                'index': idx,
                                'identifier': str(identifier),
                                'data': item
                            })
                elif data['file_type'] == 'excel':
                    df = pd.read_excel(data['file_path'])
                    id_col = None
                    for col in ['CUSTOMER_NUM', 'customer_num', 'id', 'ID', 'name', 'Name']:
                        if col in df.columns:
                            id_col = col
                            break
                    if not id_col and len(df.columns) > 0:
                        id_col = df.columns[0]

                    for idx, row in df.iterrows():
                        rows.append({
                            'index': idx,
                            'identifier': str(row[id_col]) if id_col else str(idx),
                            'data': row.to_dict()
                        })
        except Exception as e:
            return jsonify({'error': f'Error reading file: {str(e)}'}), 500

        return jsonify({'rows': rows, 'total': len(rows)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/data/<data_id>/rows/<int:row_index>', methods=['GET'])
@require_auth
def get_project_data_row(project_id, data_id, row_index):
    """Get a specific row from a data file"""
    try:
        client = get_user_client()
        result = client.table('project_data').select('*').eq(
            'id', data_id
        ).eq('project_id', project_id).single().execute()

        if not result.data:
            return jsonify({'error': 'Data not found'}), 404

        data = result.data
        row_data = None

        try:
            with open(data['file_path'], 'r', encoding='utf-8') as f:
                if data['file_type'] == 'csv':
                    df = pd.read_csv(f)
                    if row_index < len(df):
                        row_data = df.iloc[row_index].to_dict()
                elif data['file_type'] == 'json':
                    content = json.load(f)
                    if isinstance(content, list) and row_index < len(content):
                        row_data = content[row_index]
                elif data['file_type'] == 'excel':
                    df = pd.read_excel(data['file_path'])
                    if row_index < len(df):
                        row_data = df.iloc[row_index].to_dict()
        except Exception as e:
            return jsonify({'error': f'Error reading file: {str(e)}'}), 500

        if row_data is None:
            return jsonify({'error': 'Row not found'}), 404

        # Format data as text for preview
        data_text = '\n'.join([f"{k}: {v}" for k, v in row_data.items() if pd.notna(v)])

        return jsonify({
            'row': row_data,
            'data_text': data_text,
            'identifier': row_data.get('CUSTOMER_NUM') or row_data.get('id') or str(row_index)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/data/<data_id>', methods=['DELETE'])
@require_auth
def delete_project_data(project_id, data_id):
    """Delete a data file and all its rows (owner only)"""
    try:
        client = get_user_client()

        # Check if user is owner
        member_result = client.table('project_members').select('role').eq(
            'project_id', project_id
        ).eq('user_id', g.user['id']).single().execute()

        if not member_result.data or member_result.data['role'] != 'owner':
            return jsonify({'error': 'Only project owner can delete data files'}), 403

        # Get file info including upload_instance_id
        result = client.table('project_data').select('file_path, upload_instance_id').eq(
            'id', data_id
        ).eq('project_id', project_id).single().execute()

        if not result.data:
            return jsonify({'error': 'Data file not found'}), 404

        upload_instance_id = result.data.get('upload_instance_id')

        # Delete file from storage
        if result.data.get('file_path'):
            try:
                os.remove(result.data['file_path'])
            except:
                pass

        # Delete all rows associated with this upload
        if upload_instance_id:
            client.table('project_data_rows').delete().eq(
                'upload_instance_id', upload_instance_id
            ).execute()

        # Delete upload metadata
        client.table('project_data').delete().eq('id', data_id).eq('project_id', project_id).execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# PROJECT PROMPTS
# =============================================================================

@app.route('/api/projects/<project_id>/prompts', methods=['GET'])
@require_auth
def get_project_prompts(project_id):
    """Get all prompts for a project"""
    try:
        client = get_user_client()

        system_result = client.table('system_prompts').select('*').eq(
            'project_id', project_id
        ).order('version').execute()

        user_result = client.table('user_prompts').select('*').eq(
            'project_id', project_id
        ).order('version').execute()

        return jsonify({
            'system_prompts': system_result.data,
            'user_prompts': user_result.data
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/prompts/<prompt_type>/<version>', methods=['GET'])
@require_auth
def get_project_prompt_version(project_id, prompt_type, version):
    """Get a specific prompt version for a project"""
    try:
        client = get_user_client()
        table = "system_prompts" if prompt_type == "system" else "user_prompts"

        result = client.table(table).select('content, version').eq(
            'project_id', project_id
        ).eq('version', version).single().execute()

        if result.data:
            return jsonify({'content': result.data['content'], 'version': result.data['version']})
        else:
            return jsonify({'error': 'Prompt not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/prompts', methods=['POST'])
@require_auth
def create_project_prompt(project_id):
    """Create a new prompt for a project"""
    try:
        prompt_type = request.json.get('type')
        content = request.json.get('content')

        if prompt_type not in ['system', 'user']:
            return jsonify({'error': 'Invalid prompt type'}), 400
        if not content:
            return jsonify({'error': 'Content is required'}), 400

        table = 'system_prompts' if prompt_type == 'system' else 'user_prompts'
        client = get_user_client()

        # Get next version
        version_result = client.table(table).select('version').eq(
            'project_id', project_id
        ).order('version', desc=True).limit(1).execute()

        if version_result.data:
            latest = version_result.data[0]['version']
            next_version = f"{int(latest) + 1:03d}"
        else:
            next_version = "001"

        result = client.table(table).insert({
            'project_id': project_id,
            'version': next_version,
            'content': content,
            'created_by': g.user['id']
        }).execute()

        if result.data:
            return jsonify({'prompt': result.data[0]})
        return jsonify({'error': 'Failed to create prompt'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# PROJECT TEST SESSIONS
# =============================================================================

@app.route('/api/projects/<project_id>/sessions', methods=['GET'])
@require_auth
def get_project_sessions(project_id):
    """Get all test sessions for a project"""
    try:
        client = get_user_client()
        result = client.table('test_sessions').select('*').eq(
            'project_id', project_id
        ).order('created_at', desc=True).execute()

        sessions = []
        for s in result.data:
            sessions.append({
                'id': s['session_id'],
                'timestamp': s['created_at'][:19].replace('T', ' '),
                'model': s['model'],
                'system_version': s['system_version'],
                'user_version': s['user_version'],
                'total_customers': s['total_customers'],
                'completed': s['completed_customers'],
                'status': s['status'],
                'avg_scores': {
                    'completeness': float(s['avg_completeness']) if s['avg_completeness'] else 0,
                    'faithfulness': float(s['avg_faithfulness']) if s['avg_faithfulness'] else 0,
                    'fluency': float(s['avg_fluency']) if s['avg_fluency'] else 0,
                    'analysis_quality': float(s['avg_analysis_quality']) if s['avg_analysis_quality'] else 0
                }
            })

        return jsonify({'sessions': sessions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/projects/<project_id>/sessions', methods=['POST'])
@require_auth
def start_project_test_session(project_id):
    """Start a new test session for a project"""
    try:
        system_version = request.json.get('system_version')
        user_version = request.json.get('user_version')
        model = request.json.get('model', 'google/gemma-3-27b-it')
        data_id = request.json.get('data_id')  # Which data file to test against

        client = get_user_client()

        # Get data file
        data_result = client.table('project_data').select('*').eq(
            'id', data_id
        ).eq('project_id', project_id).single().execute()

        if not data_result.data:
            return jsonify({'error': 'Data file not found'}), 404

        data_file = data_result.data

        # Load data content
        with open(data_file['file_path'], 'r', encoding='utf-8') as f:
            if data_file['file_type'] == 'csv':
                df = pd.read_csv(f)
                records = df.to_dict('records')
            elif data_file['file_type'] == 'json':
                records = json.load(f)
            else:
                return jsonify({'error': 'Unsupported data format for testing'}), 400

        session_id = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Create session in database
        client.table('test_sessions').insert({
            'session_id': session_id,
            'project_id': project_id,
            'user_id': g.user['id'],
            'system_version': system_version,
            'user_version': user_version,
            'model': model,
            'total_customers': len(records),
            'completed_customers': 0,
            'status': 'running'
        }).execute()

        return jsonify({
            'session_id': session_id,
            'total_customers': len(records),
            'records': records
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# LEGACY SUPPORT - Original routes for backward compatibility
# =============================================================================

def get_prompt_versions(prompt_type):
    """Get list of available versions for a prompt type (system or user)"""
    db_versions = get_prompt_versions_from_supabase(prompt_type)
    if db_versions is not None:
        return db_versions
    pattern = os.path.join(PROMPTS_PATH, f"{prompt_type}_prompt_*.txt")
    files = glob.glob(pattern)
    versions = []
    for f in files:
        match = re.search(r'_(\d{3})\.txt$', f)
        if match:
            versions.append(match.group(1))
    return sorted(versions)

def get_latest_version(prompt_type):
    versions = get_prompt_versions(prompt_type)
    return versions[-1] if versions else "000"

def get_next_version(prompt_type):
    latest = get_latest_version(prompt_type)
    return f"{int(latest) + 1:03d}"

def load_prompt(prompt_type, version=None):
    if version is None:
        version = get_latest_version(prompt_type)
    content = load_prompt_from_supabase(prompt_type, version)
    if content is not None:
        return content
    prompt_path = os.path.join(PROMPTS_PATH, f"{prompt_type}_prompt_{version}.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()

def save_prompt(prompt_type, content, version=None):
    if version is None:
        version = get_next_version(prompt_type)
    prompt_path = os.path.join(PROMPTS_PATH, f"{prompt_type}_prompt_{version}.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(content)
    save_prompt_to_supabase(prompt_type, version, content)
    return version

def get_prompt_versions_from_supabase(prompt_type):
    if not supabase:
        return None
    try:
        table = "system_prompts" if prompt_type == "system" else "user_prompts"
        result = supabase.table(table).select("version").is_("project_id", "null").order("version").execute()
        return [r['version'] for r in result.data]
    except Exception as e:
        print(f"Supabase get versions error: {e}")
        return None

def load_prompt_from_supabase(prompt_type, version):
    if not supabase:
        return None
    try:
        table = "system_prompts" if prompt_type == "system" else "user_prompts"
        result = supabase.table(table).select("content").eq("version", version).is_("project_id", "null").single().execute()
        return result.data['content'] if result.data else None
    except Exception as e:
        print(f"Supabase load prompt error: {e}")
        return None

def save_prompt_to_supabase(prompt_type, version, content):
    if not supabase:
        return
    try:
        table = "system_prompts" if prompt_type == "system" else "user_prompts"
        supabase.table(table).upsert({
            "version": version,
            "content": content,
            "updated_at": datetime.now().isoformat()
        }, on_conflict="version").execute()
    except Exception as e:
        print(f"Supabase prompt save error: {e}")

def save_run_to_supabase(customer_num, run_data, input_text):
    if not supabase:
        return
    try:
        supabase.table("customer_runs").insert({
            "run_id": run_data['id'],
            "customer_num": customer_num,
            "input_text": input_text,
            "output_text": run_data['summary'],
            "system_version": run_data['system_version'],
            "user_version": run_data['user_version'],
            "model": run_data['model'],
            "elapsed_seconds": run_data['elapsed'],
            "score_completeness": run_data['scores'].get('completeness'),
            "score_faithfulness": run_data['scores'].get('faithfulness'),
            "score_fluency": run_data['scores'].get('fluency'),
            "score_analysis_quality": run_data['scores'].get('analysis_quality')
        }).execute()
    except Exception as e:
        print(f"Supabase run save error: {e}")

def save_test_session_to_supabase(session_data):
    if not supabase:
        return
    try:
        supabase.table("test_sessions").upsert({
            "session_id": session_data['id'],
            "system_version": session_data['system_version'],
            "user_version": session_data['user_version'],
            "model": session_data['model'],
            "total_customers": session_data['total_customers'],
            "completed_customers": session_data['completed'],
            "status": session_data['status'],
            "avg_completeness": session_data['avg_scores'].get('completeness'),
            "avg_faithfulness": session_data['avg_scores'].get('faithfulness'),
            "avg_fluency": session_data['avg_scores'].get('fluency'),
            "avg_analysis_quality": session_data['avg_scores'].get('analysis_quality'),
            "updated_at": datetime.now().isoformat()
        }, on_conflict="session_id").execute()
    except Exception as e:
        print(f"Supabase session save error: {e}")

def save_test_result_to_supabase(session_id, result):
    if not supabase:
        return
    try:
        supabase.table("test_results").insert({
            "session_id": session_id,
            "customer_num": result['customer'],
            "input_text": result['input'],
            "output_text": result['output'],
            "score_completeness": result['scores'].get('completeness'),
            "score_faithfulness": result['scores'].get('faithfulness'),
            "score_fluency": result['scores'].get('fluency'),
            "score_analysis_quality": result['scores'].get('analysis_quality'),
            "elapsed_seconds": result['elapsed']
        }).execute()
    except Exception as e:
        print(f"Supabase test result save error: {e}")

def load_company_runs_from_supabase(customer_num):
    if not supabase:
        return None
    try:
        result = supabase.table("customer_runs").select("*").eq("customer_num", customer_num).is_("project_id", "null").order("created_at", desc=True).execute()
        runs = []
        for r in result.data:
            runs.append({
                'id': r['run_id'],
                'timestamp': r['created_at'][:19].replace('T', ' '),
                'system_version': r['system_version'],
                'user_version': r['user_version'],
                'model': r['model'],
                'elapsed': float(r['elapsed_seconds']) if r['elapsed_seconds'] else 0,
                'summary': r['output_text'],
                'scores': {
                    'completeness': r['score_completeness'] or 0,
                    'faithfulness': r['score_faithfulness'] or 0,
                    'fluency': r['score_fluency'] or 0,
                    'analysis_quality': r['score_analysis_quality'] or 0
                }
            })
        return runs
    except Exception as e:
        print(f"Supabase load runs error: {e}")
        return None

def get_all_sessions_from_supabase():
    if not supabase:
        return None
    try:
        result = supabase.table("test_sessions").select("*").is_("project_id", "null").order("created_at", desc=True).execute()
        sessions = []
        for s in result.data:
            sessions.append({
                'id': s['session_id'],
                'timestamp': s['created_at'][:19].replace('T', ' '),
                'model': s['model'],
                'system_version': s['system_version'],
                'user_version': s['user_version'],
                'total_customers': s['total_customers'],
                'completed': s['completed_customers'],
                'status': s['status'],
                'avg_scores': {
                    'completeness': float(s['avg_completeness']) if s['avg_completeness'] else 0,
                    'faithfulness': float(s['avg_faithfulness']) if s['avg_faithfulness'] else 0,
                    'fluency': float(s['avg_fluency']) if s['avg_fluency'] else 0,
                    'analysis_quality': float(s['avg_analysis_quality']) if s['avg_analysis_quality'] else 0
                }
            })
        return sessions
    except Exception as e:
        print(f"Supabase get sessions error: {e}")
        return None

def load_session_from_supabase(session_id):
    if not supabase:
        return None
    try:
        session_result = supabase.table("test_sessions").select("*").eq("session_id", session_id).single().execute()
        if not session_result.data:
            return None
        s = session_result.data
        results_result = supabase.table("test_results").select("*").eq("session_id", session_id).execute()
        results = []
        for r in results_result.data:
            results.append({
                'customer': r['customer_num'],
                'input': r['input_text'],
                'output': r['output_text'],
                'scores': {
                    'completeness': r['score_completeness'] or 0,
                    'faithfulness': r['score_faithfulness'] or 0,
                    'fluency': r['score_fluency'] or 0,
                    'analysis_quality': r['score_analysis_quality'] or 0
                },
                'elapsed': float(r['elapsed_seconds']) if r['elapsed_seconds'] else 0
            })
        return {
            'id': s['session_id'],
            'timestamp': s['created_at'][:19].replace('T', ' '),
            'system_version': s['system_version'],
            'user_version': s['user_version'],
            'model': s['model'],
            'total_customers': s['total_customers'],
            'completed': s['completed_customers'],
            'status': s['status'],
            'results': results,
            'avg_scores': {
                'completeness': float(s['avg_completeness']) if s['avg_completeness'] else 0,
                'faithfulness': float(s['avg_faithfulness']) if s['avg_faithfulness'] else 0,
                'fluency': float(s['avg_fluency']) if s['avg_fluency'] else 0,
                'analysis_quality': float(s['avg_analysis_quality']) if s['avg_analysis_quality'] else 0
            }
        }
    except Exception as e:
        print(f"Supabase load session error: {e}")
        return None

# Run History Management
def get_company_runs_file(company_name):
    safe_name = re.sub(r'[^\w\s-]', '', company_name).strip().replace(' ', '_')
    return os.path.join(RUNS_PATH, f"{safe_name}.json")

def load_company_runs(company_name):
    db_runs = load_company_runs_from_supabase(company_name)
    if db_runs is not None:
        return db_runs
    runs_file = get_company_runs_file(company_name)
    if os.path.exists(runs_file):
        with open(runs_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_run(company_name, run_data, input_text=""):
    runs = load_company_runs(company_name)
    runs.append(run_data)
    runs_file = get_company_runs_file(company_name)
    with open(runs_file, 'w', encoding='utf-8') as f:
        json.dump(runs, f, ensure_ascii=False, indent=2)
    save_run_to_supabase(company_name, run_data, input_text)
    return len(runs) - 1

# API Call
def call_gemma_api(user_data, system_version=None, user_version=None, model=None, company_name=None):
    if model is None:
        model = "google/gemma-3-27b-it"
    system_prompt = load_prompt("system", system_version)
    user_prompt_template = load_prompt("user", user_version)
    user_prompt = user_prompt_template.replace("{data_rows}", user_data)
    user_prompt = user_prompt.replace("{company_name}", company_name or "")
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1500,
            "top_p": 0.9
        },
        timeout=90
    )
    result = response.json()
    if "choices" in result:
        return result["choices"][0]["message"]["content"]
    else:
        raise Exception(f"API Error: {result.get('error', result)}")

# Validation
def validate_output(input_text, output_text):
    validation_prompt = """You are an expert evaluator. Analyze the INPUT (rule-based sentences) and OUTPUT (rewritten summary) and score three criteria.

IMPORTANT:
Be very strict and do not dismiss any mismatches. Try to cut as much point as possible to help best model win.

INPUT (Original rule-based sentences):
{input_text}

OUTPUT (Generated summary):
{output_text}

Score each criterion between 0 and 100:

1. COMPLETENESS: Does the output include ALL facts, numbers, and information from the input? Check every single data point.
   - 100 = Every fact preserved
   - 0 = Any product name or numerical information missing

2. FAITHFULNESS: Does the output ONLY use information from the input? No additions, assumptions, or hallucinations?
   - 100 = Perfectly faithful, no extra information
   - 0 = Any comment that is not directly extracted from input or contains fabricated information

3. FLUENCY: Is the output clear, coherent, natural language with logical flow?
   - 100 = Excellent, professional writing
   - 0 = Incoherent or unnatural

4. ANALYSIS QUALITY: Does the output provide a clear and concise analysis of the input? Check every single comment added by the model.
   - 100 = Few comments with correct and concise analysis
   - 0 = Number of comments is high or some comments are inaccurate or no comments exist, too much comments or inaccurate comments

Respond ONLY with a JSON object in this exact format:
{{"completeness": <score>, "faithfulness": <score>, "fluency": <score>, "analysis_quality": <score>}}"""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": validation_prompt.format(input_text=input_text, output_text=output_text)}],
                "temperature": 0.1,
                "max_tokens": 100
            },
            timeout=30
        )
        result = response.json()
        if "choices" in result:
            content = result["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            scores = json.loads(content.strip())
            return {
                "completeness": int(scores.get("completeness", 0)),
                "faithfulness": int(scores.get("faithfulness", 0)),
                "fluency": int(scores.get("fluency", 0)),
                "analysis_quality": int(scores.get("analysis_quality", 0))
            }
    except Exception as e:
        print(f"Validation error: {e}")
    return {"completeness": -1, "faithfulness": -1, "fluency": -1, "analysis_quality": -1}

# Data Functions
def load_rule_based_data():
    data = {}
    file_path = os.path.join(DATA_PATH, "rule_based.txt")
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(';', 1)
            if len(parts) == 2:
                customer_num = parts[0].strip()
                sentences = parts[1].strip()
                data[customer_num] = sentences
    return data

def get_company_list():
    data = load_rule_based_data()
    companies = [{'CUSTOMER_NUM': num, 'CUSTOMER_NAME': num} for num in sorted(data.keys())]
    return companies

def get_company_data(customer_num):
    data = load_rule_based_data()
    customer_num_str = str(customer_num).strip()
    if customer_num_str in data:
        return customer_num_str, data[customer_num_str]
    return None, None

# Session Management
def get_session_file(session_id):
    return os.path.join(SESSIONS_PATH, f"{session_id}.json")

def load_session(session_id):
    db_session = load_session_from_supabase(session_id)
    if db_session is not None:
        return db_session
    session_file = get_session_file(session_id)
    if os.path.exists(session_file):
        with open(session_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_session(session_data, new_result=None):
    session_file = get_session_file(session_data['id'])
    with open(session_file, 'w', encoding='utf-8') as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)
    save_test_session_to_supabase(session_data)
    if new_result:
        save_test_result_to_supabase(session_data['id'], new_result)

def get_all_sessions():
    db_sessions = get_all_sessions_from_supabase()
    if db_sessions is not None:
        return db_sessions
    sessions = []
    for f in glob.glob(os.path.join(SESSIONS_PATH, "*.json")):
        try:
            with open(f, 'r', encoding='utf-8') as file:
                session = json.load(file)
                sessions.append({
                    'id': session['id'],
                    'timestamp': session['timestamp'],
                    'model': session['model'],
                    'system_version': session['system_version'],
                    'user_version': session['user_version'],
                    'total_customers': session.get('total_customers', 0),
                    'completed': session.get('completed', 0),
                    'status': session.get('status', 'unknown'),
                    'avg_scores': session.get('avg_scores', {})
                })
        except:
            pass
    return sorted(sessions, key=lambda x: x['timestamp'], reverse=True)

def analyze_low_scores(session_id, threshold=50):
    session = load_session(session_id)
    if not session:
        return None
    results = session.get('results', [])
    low_score_customers = []
    for r in results:
        scores = r.get('scores', {})
        if any(scores.get(k, 100) < threshold for k in ['completeness', 'faithfulness', 'fluency', 'analysis_quality']):
            low_score_customers.append({
                'customer': r['customer'],
                'scores': scores,
                'input': r.get('input', ''),
                'output': r.get('output', ''),
                'issues': []
            })
            if scores.get('completeness', 100) < threshold:
                low_score_customers[-1]['issues'].append('completeness')
            if scores.get('faithfulness', 100) < threshold:
                low_score_customers[-1]['issues'].append('faithfulness')
            if scores.get('fluency', 100) < threshold:
                low_score_customers[-1]['issues'].append('fluency')
            if scores.get('analysis_quality', 100) < threshold:
                low_score_customers[-1]['issues'].append('analysis_quality')
    issue_counts = {'completeness': 0, 'faithfulness': 0, 'fluency': 0, 'analysis_quality': 0}
    for c in low_score_customers:
        for issue in c['issues']:
            issue_counts[issue] += 1
    return {
        'total_low_score': len(low_score_customers),
        'issue_distribution': issue_counts,
        'customers': low_score_customers[:10]
    }

# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/app')
def index():
    companies = get_company_list()
    system_versions = get_prompt_versions("system")
    user_versions = get_prompt_versions("user")
    return render_template('index.html',
                          companies=companies,
                          system_versions=system_versions,
                          user_versions=user_versions,
                          supabase_url=SUPABASE_URL,
                          supabase_anon_key=SUPABASE_KEY)

@app.route('/get_company_data/<customer_num>')
def get_company_data_route(customer_num):
    try:
        company_name, data = get_company_data(customer_num)
        if data is None:
            return jsonify({'error': 'Müşteri bulunamadı'}), 404
        return jsonify({'data': data, 'company_name': company_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_prompt/<prompt_type>/<version>')
def get_prompt(prompt_type, version):
    try:
        content = load_prompt(prompt_type, version)
        return jsonify({'content': content, 'version': version})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/save_prompt', methods=['POST'])
def save_prompt_route():
    try:
        prompt_type = request.json.get('type')
        content = request.json.get('content')
        if prompt_type not in ['system', 'user']:
            return jsonify({'error': 'Geçersiz prompt tipi'}), 400
        version = save_prompt(prompt_type, content)
        return jsonify({'version': version, 'message': f'Versiyon {version} kaydedildi'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_versions')
def get_versions():
    return jsonify({
        'system': get_prompt_versions("system"),
        'user': get_prompt_versions("user")
    })

@app.route('/summarize', methods=['POST'])
def summarize():
    try:
        data = request.json.get('data', '')
        system_version = request.json.get('system_version')
        user_version = request.json.get('user_version')
        model = request.json.get('model')
        company_name = request.json.get('company_name', 'Bilinmeyen')
        if not data.strip():
            return jsonify({'error': 'Veri girilmedi'}), 400
        start_time = time.time()
        summary = call_gemma_api(data, system_version, user_version, model, company_name)
        elapsed = round(time.time() - start_time, 1)
        scores = validate_output(data, summary)
        run_data = {
            'id': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'system_version': system_version,
            'user_version': user_version,
            'model': model or 'google/gemma-3-27b-it',
            'elapsed': elapsed,
            'summary': summary,
            'scores': scores
        }
        run_index = save_run(company_name, run_data, data)
        return jsonify({
            'summary': summary,
            'run_id': run_data['id'],
            'elapsed': elapsed,
            'scores': scores
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_runs/<company_name>')
def get_runs(company_name):
    try:
        runs = load_company_runs(company_name)
        run_list = [{
            'id': r['id'],
            'timestamp': r['timestamp'],
            'model': r['model'].split('/')[-1].replace('-it', ''),
            'sys_version': r['system_version'],
            'usr_version': r['user_version'],
            'elapsed': r['elapsed'],
            'scores': r.get('scores', {})
        } for r in runs]
        return jsonify({'runs': run_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_run_details/<company_name>/<run_id>')
def get_run_details(company_name, run_id):
    try:
        runs = load_company_runs(company_name)
        for run in runs:
            if run['id'] == run_id:
                return jsonify(run)
        return jsonify({'error': 'Run bulunamadı'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_sessions')
def get_sessions():
    try:
        sessions = get_all_sessions()
        return jsonify({'sessions': sessions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_test_session', methods=['POST'])
def start_test_session():
    try:
        system_version = request.json.get('system_version')
        user_version = request.json.get('user_version')
        model = request.json.get('model', 'google/gemma-3-27b-it')
        session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        companies = get_company_list()
        session_data = {
            'id': session_id,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'system_version': system_version,
            'user_version': user_version,
            'model': model,
            'total_customers': len(companies),
            'completed': 0,
            'status': 'running',
            'results': [],
            'avg_scores': {'completeness': 0, 'faithfulness': 0, 'fluency': 0, 'analysis_quality': 0}
        }
        save_session(session_data)
        return jsonify({
            'session_id': session_id,
            'total_customers': len(companies),
            'customers': [c['CUSTOMER_NUM'] for c in companies]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/run_single_test', methods=['POST'])
def run_single_test():
    try:
        session_id = request.json.get('session_id')
        customer_num = request.json.get('customer_num')
        session = load_session(session_id)
        if not session:
            return jsonify({'error': 'Session bulunamadı'}), 404
        _, input_data = get_company_data(customer_num)
        if not input_data:
            return jsonify({'error': 'Müşteri verisi bulunamadı'}), 404
        start_time = time.time()
        output = call_gemma_api(
            input_data,
            session['system_version'],
            session['user_version'],
            session['model'],
            customer_num
        )
        elapsed = round(time.time() - start_time, 1)
        scores = validate_output(input_data, output)
        result = {
            'customer': customer_num,
            'input': input_data,
            'output': output,
            'scores': scores,
            'elapsed': elapsed
        }
        session['results'].append(result)
        session['completed'] += 1
        valid_results = [r for r in session['results'] if r['scores'].get('completeness', -1) >= 0]
        if valid_results:
            for key in ['completeness', 'faithfulness', 'fluency', 'analysis_quality']:
                session['avg_scores'][key] = round(
                    sum(r['scores'].get(key, 0) for r in valid_results) / len(valid_results), 1
                )
        if session['completed'] >= session['total_customers']:
            session['status'] = 'completed'
        save_session(session, result)
        return jsonify({
            'customer': customer_num,
            'scores': scores,
            'elapsed': elapsed,
            'completed': session['completed'],
            'total': session['total_customers'],
            'avg_scores': session['avg_scores']
        })
    except Exception as e:
        return jsonify({'error': str(e), 'customer': request.json.get('customer_num')}), 500

@app.route('/get_session_details/<session_id>')
def get_session_details(session_id):
    try:
        session = load_session(session_id)
        if not session:
            return jsonify({'error': 'Session bulunamadı'}), 404
        return jsonify(session)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_session_analysis/<session_id>')
def get_session_analysis(session_id):
    try:
        threshold = request.args.get('threshold', 50, type=int)
        analysis = analyze_low_scores(session_id, threshold)
        if not analysis:
            return jsonify({'error': 'Session bulunamadı'}), 404
        return jsonify(analysis)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/compare_sessions', methods=['POST'])
def compare_sessions():
    try:
        session_ids = request.json.get('session_ids', [])
        if len(session_ids) < 2:
            return jsonify({'error': 'En az 2 session seçin'}), 400
        sessions = []
        for sid in session_ids:
            session = load_session(sid)
            if session:
                sessions.append(session)
        if len(sessions) < 2:
            return jsonify({'error': 'Sessionlar bulunamadı'}), 404
        comparison = {
            'sessions': [{
                'id': s['id'],
                'timestamp': s['timestamp'],
                'model': s['model'],
                'system_version': s['system_version'],
                'user_version': s['user_version'],
                'avg_scores': s.get('avg_scores', {})
            } for s in sessions],
            'customer_comparison': []
        }
        customer_results = {}
        for session in sessions:
            for result in session.get('results', []):
                cust = result['customer']
                if cust not in customer_results:
                    customer_results[cust] = {}
                customer_results[cust][session['id']] = result['scores']
        for cust, scores_by_session in customer_results.items():
            if len(scores_by_session) >= 2:
                score_values = list(scores_by_session.values())
                max_diff = 0
                for key in ['completeness', 'faithfulness', 'fluency', 'analysis_quality']:
                    vals = [s.get(key, 0) for s in score_values]
                    diff = max(vals) - min(vals)
                    max_diff = max(max_diff, diff)
                if max_diff > 10:
                    comparison['customer_comparison'].append({
                        'customer': cust,
                        'scores': scores_by_session,
                        'max_diff': max_diff
                    })
        comparison['customer_comparison'].sort(key=lambda x: x['max_diff'], reverse=True)
        comparison['customer_comparison'] = comparison['customer_comparison'][:20]
        return jsonify(comparison)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)
