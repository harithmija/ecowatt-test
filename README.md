# EcoWatt AI

    pip install -r requirements.txt
    $env:GEMINI_API_KEY = Read-Host "Enter your Gemini API key"
    python -m uvicorn server:app --reload

The API key is optional. Without it, the built-in rules answer. In PowerShell, set the environment variable in the same terminal before starting Uvicorn.

The app provides resident sign-up and sign-in. Accounts and hashed passwords are stored in `ecowatt.db`; browser sessions use an HTTP-only cookie and expire after seven days. Passwords must be at least 12 characters.

Google sign-in is also supported. Create a Google OAuth 2.0 **Web application** client ID in Google Cloud Console, add the app origin (for local development, `http://localhost:8000` and/or `http://127.0.0.1:8000`) to its authorized JavaScript origins, then set the client ID before starting Uvicorn:

    $env:GOOGLE_CLIENT_ID = "your-client-id.apps.googleusercontent.com"
    python -m uvicorn server:app --reload

The client ID is public configuration, not a password. Google sign-in is hidden as unavailable until it is configured. The server verifies Google's ID token and requires a verified email before creating or linking a resident account. Existing accounts can be linked by the same verified Google email.

For a deployment over HTTPS, set `$env:COOKIE_SECURE = "1"` before starting Uvicorn. Do not expose this demo publicly without adding appropriate rate limiting and separate storage/access controls for real household data.

The dashboard includes the Eco Score overview, detailed/simple view toggle, interactive home map, appliance action log, budget and challenges, shareable weekly recap, bill explainer, hourly scheduler, month comparison, device readings, dark mode, and energy tips. To enable sensor reading ingestion, set a private token in the same PowerShell window before starting Uvicorn:

    $env:INGEST_TOKEN = Read-Host "Enter a private sensor-ingestion token"

The token is required for `POST /api/readings`; sensor clients must send it in the `X-Token` header. The resident must also be signed in.

Simulated readings are generated on first run into `ecowatt.db`. All resident accounts currently see the same simulated household data. Delete the database file to regenerate readings; this also deletes accounts, sessions, and saved actions.

To use real hardware later, insert rows into `readings` with `source='sensor'`.
