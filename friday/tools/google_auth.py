"""Google OAuth2 helper — shared by Gmail and Calendar tools.

Setup:
1. Go to https://console.cloud.google.com
2. Create a project → Enable Gmail API + Calendar API
3. Create OAuth2 credentials (Desktop app OR Web application)
   - Desktop app: simplest, no redirect URI needed
   - Web application: set redirect URI to http://localhost:8080/
4. Download the JSON → save as ~/.friday/google_credentials.json
5. Run: uv run python -m friday.tools.google_auth
   This opens a browser for OAuth consent and saves the token.
"""

import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

FRIDAY_DIR = Path.home() / ".friday"
CREDENTIALS_FILE = FRIDAY_DIR / "google_credentials.json"
TOKEN_FILE = FRIDAY_DIR / "google_token.json"

# Gmail + Calendar read/write scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def _detect_app_type(creds_path: Path) -> str:
    """Detect if credentials are for Desktop or Web application."""
    data = json.loads(creds_path.read_text())
    if "installed" in data:
        return "desktop"
    elif "web" in data:
        return "web"
    return "unknown"


def get_credentials() -> Credentials | None:
    """Get valid Google OAuth2 credentials, or None if not set up."""
    if not CREDENTIALS_FILE.exists():
        return None

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
            return creds
        except Exception:
            # Token refresh failed — need re-auth
            TOKEN_FILE.unlink(missing_ok=True)
            return None

    return None


def authenticate():
    """Run the OAuth2 flow interactively. Works with both Desktop and Web app credentials."""
    FRIDAY_DIR.mkdir(exist_ok=True)

    if not CREDENTIALS_FILE.exists():
        print(f"Missing: {CREDENTIALS_FILE}")
        print("Download OAuth2 credentials from Google Cloud Console")
        print("and save as ~/.friday/google_credentials.json")
        print()
        print("Either Desktop app or Web application type works:")
        print("  Desktop app  — simplest, no redirect URI config needed")
        print("  Web app      — set redirect URI to http://localhost:8080/")
        return

    app_type = _detect_app_type(CREDENTIALS_FILE)
    print(f"Detected credential type: {app_type}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE), SCOPES
    )

    if app_type == "web":
        # Web app credentials — use fixed port so redirect URI matches
        print("Using localhost:8080 redirect (make sure this matches your Google Cloud redirect URI)")
        creds = flow.run_local_server(port=8080)
    else:
        # Desktop app — any available port
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"\nToken saved to {TOKEN_FILE}")
    print("Gmail and Calendar access configured.")


def is_configured() -> bool:
    """Check if Google API credentials are set up and valid."""
    return get_credentials() is not None


if __name__ == "__main__":
    authenticate()
