"""Google OAuth2 helper — shared by Gmail and Calendar tools.

FRIDAY ships with a bundled OAuth client at ``friday/data/google_client.json``
so users can just run ``friday setup gmail``, click through the consent
screen, and be done — no GCP project creation required.

OAuth client resolution order:
    1. ``friday/data/google_client.json``    — bundled (shared FRIDAY client)
    2. ``~/.friday/google_credentials.json`` — bring-your-own (power users)

The per-user access / refresh token is cached at ``~/.friday/google_token.json``
regardless of which client is used.

Note: because Gmail uses sensitive scopes and the shared FRIDAY client is not
(yet) verified by Google, users will see Google's "This app isn't verified"
warning once, and have to click Advanced → Continue. That's normal for every
unverified Google OAuth app.
"""

import json
import urllib.request
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

FRIDAY_DIR = Path.home() / ".friday"
BUNDLED_CLIENT = Path(__file__).parent.parent / "data" / "google_client.json"
USER_CLIENT = FRIDAY_DIR / "google_credentials.json"
TOKEN_FILE = FRIDAY_DIR / "google_token.json"


def _active_client_path() -> Path | None:
    """Resolve which OAuth client FRIDAY should use. Bundled wins; user override secondary."""
    if BUNDLED_CLIENT.exists():
        return BUNDLED_CLIENT
    if USER_CLIENT.exists():
        return USER_CLIENT
    return None


# Back-compat alias — older callers read CREDENTIALS_FILE directly.
CREDENTIALS_FILE = _active_client_path() or USER_CLIENT

# Gmail + Calendar read/write scopes. userinfo.* lets us read the signed-in
# user's name + email so the Mac app can show them in the profile footer.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]


def fetch_user_profile(creds: Credentials) -> dict:
    """Hit Google's userinfo endpoint. Returns {email, name, picture} or {}."""
    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
        data = json.loads(body)
        return {
            "email": data.get("email", ""),
            "name": data.get("name", "") or data.get("given_name", ""),
            "picture": data.get("picture", ""),
        }
    except Exception:
        return {}


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
    if not _active_client_path():
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
    """Run the OAuth2 flow interactively."""
    FRIDAY_DIR.mkdir(exist_ok=True)

    client_path = _active_client_path()
    if not client_path:
        # This shouldn't happen with the bundled client, but just in case someone
        # stripped friday/data/google_client.json from their install.
        print("No OAuth client found. Expected either:")
        print(f"  · bundled:  {BUNDLED_CLIENT}  (should ship with FRIDAY)")
        print(f"  · user:     {USER_CLIENT}      (bring-your-own GCP client)")
        return

    using_bundled = (client_path == BUNDLED_CLIENT)
    if using_bundled:
        print("Using FRIDAY's shared OAuth client.")
        print("Heads up: you'll see a Google 'unverified app' warning — click")
        print("Advanced → 'Go to FRIDAY (unsafe)'. That's normal for community-built")
        print("tools until Google's app verification clears. Your data is only")
        print("flowing between your browser, Google, and your local machine.")
        print()
    else:
        print(f"Using your own OAuth client at {client_path}.")

    app_type = _detect_app_type(client_path)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)

    if app_type == "web":
        print("Using localhost:8080 redirect (must match your Google Cloud redirect URI)")
        creds = flow.run_local_server(port=8080)
    else:
        # Desktop app — any available port
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"\nToken saved to {TOKEN_FILE}")
    print("Gmail and Calendar access configured.")

    # Emit machine-readable auth line for the Mac app to parse.
    profile = fetch_user_profile(creds)
    email = profile.get("email", "")
    name = profile.get("name", "")
    print(f"AUTHENTICATED: {email}|{name}")


def is_configured() -> bool:
    """Check if Google API credentials are set up and valid."""
    return get_credentials() is not None


if __name__ == "__main__":
    authenticate()
