"""Refresh YouTube OAuth token. Run from Windows PowerShell with: py scripts/refresh_youtube_token.py"""

from google_auth_oauthlib.flow import InstalledAppFlow

CREDS_DIR = r"\\wsl$\Ubuntu\home\wkoch\.credentials\antikythera-f1"

flow = InstalledAppFlow.from_client_secrets_file(
    CREDS_DIR + r"\youtube_client_secret.json",
    [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ],
)
creds = flow.run_local_server(port=9123)

token_path = CREDS_DIR + r"\youtube_token.json"
with open(token_path, "w") as f:
    f.write(creds.to_json())

print(f"Token refreshed successfully -> {token_path}")
