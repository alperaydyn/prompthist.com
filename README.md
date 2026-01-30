# PromptHist

A web application for prompt testing and history management with multi-user project support.

## Features

- **Project Management**: Create and manage multiple projects with team collaboration
- **Data Upload**: Upload CSV/Excel files for data-driven prompt testing
- **Prompt Templates**: Create and version system and user prompts
- **Preview Panel**: Preview data rows before testing
- **Test Execution**: Run prompts against uploaded data with AI models
- **Team Collaboration**: Invite team members to projects with role-based access

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: Supabase (PostgreSQL with Row Level Security)
- **Authentication**: Supabase Auth (Email/Password, Google OAuth)
- **AI Integration**: OpenRouter API
- **Frontend**: Vanilla JavaScript with modern CSS

## Setup

1. Clone the repository
2. Create a `.env` file with the following variables:
   ```
   OPENROUTER_API_KEY=your_openrouter_api_key
   SUPABASE_PROJECT_URL=your_supabase_url
   SUPABASE_ANON_KEY=your_supabase_anon_key

   # Email Configuration (optional, for invitations)
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your_email
   SMTP_PASSWORD=your_app_password
   SMTP_FROM_EMAIL=your_email
   SMTP_FROM_NAME=PromptHist
   ```

3. Install dependencies:
   ```bash
   pip install flask supabase pandas python-dotenv requests openpyxl
   ```

4. Run the application:
   ```bash
   python app.py
   ```

5. Access the application at `http://localhost:5001`

## Database Schema

The application uses Supabase with the following main tables:
- `projects` - Project metadata
- `project_members` - Project membership and roles
- `project_invitations` - Pending invitations
- `project_data` - Uploaded file metadata
- `project_data_rows` - Imported data rows
- `prompts` - Prompt templates with versioning
- `sessions` - Test session results

## License

MIT
