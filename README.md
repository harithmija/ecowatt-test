# EcoWatt AI

    pip install -r requirements.txt
    $env:GEMINI_API_KEY = Read-Host "Enter your Gemini API key"
    python -m uvicorn server:app --reload
    if cannot
    python -m uvicorn server:app --reload --host 127.0.0.1 --port 8001(try use other port)
    http://127.0.0.1:8001/


The API key is optional. Without it, the built-in rules answer. In PowerShell, set the environment variable in the same terminal before starting Uvicorn.

The app provides resident sign-up and sign-in. Accounts and hashed passwords are stored in `ecowatt.db`; browser sessions use an HTTP-only cookie and expire after seven days. Passwords must be at least 12 characters.

Appliance recommendations can be selected and logged with an estimated monthly kWh and bill impact. For simulated readings, the selected action's estimated reduction is applied to later hourly readings for that appliance, so the monitor reflects the action; real sensor readings are never changed. Free-text action notes are logged without changing readings because no reduction is defined. Estimates are illustrative and actual savings vary.

Overview alerts compare each recommended action from the last seven days with the appliance's average daily use over the seven days before the action. A comparison appears after readings from a later day are available; simulated changes are clearly labeled as illustrative and do not prove the action caused the change.

The Smart Scheduler learns timestamped usage patterns for all appliances; it combines lights across rooms as **Lights** and fans across rooms as **Fans**. It presents the learned routines and a readable seven-day “when to use / when to save” guide. The latest seven days are compared with earlier stable behavior so a recent AC increase is highlighted rather than learned as normal. Recommendations focus on avoiding unnecessary use; the scheduler does not control appliances, switch off refrigerators, or prioritize energy shifting. Keep comfort and appliance safety instructions first. Budget pace and the daily energy allowance are shown in Budget & Goals. On the current flat-rate tariff, reducing energy use—not moving it to another hour—is what can lower the bill. Demo behavior is simulated and shared across accounts.

Google sign-in is also supported. Create a Google OAuth 2.0 **Web application** client ID in Google Cloud Console, add the app origin (for local development, `http://localhost:8000` and/or `http://127.0.0.1:8000`) to its authorized JavaScript origins, then set the client ID before starting Uvicorn:

    $env:GOOGLE_CLIENT_ID = "your-client-id.apps.googleusercontent.com"
    python -m uvicorn server:app --reload

The client ID is public configuration, not a password. Google sign-in is hidden as unavailable until it is configured. The server verifies Google's ID token and requires a verified email before creating or linking a resident account. Existing accounts can be linked by the same verified Google email.

For a deployment over HTTPS, set `$env:COOKIE_SECURE = "1"` before starting Uvicorn. Do not expose this demo publicly without adding appropriate rate limiting and separate storage/access controls for real household data.

The dashboard includes the Eco Score overview, detailed/simple view toggle, interactive home map, appliance action log, budget and challenges, shareable weekly recap, hourly scheduler, month comparison, device readings, dark mode, and energy tips. To enable sensor reading ingestion, set a private token in the same PowerShell window before starting Uvicorn:

The Home Map groups appliances by room, shows each room's current-month electricity use, and highlights the room using the most. Simulated household readings include bedroom, kitchen, living-room, bathroom, and laundry lights, fans, and a television alongside the larger appliances; these are illustrative demo readings, not live device measurements.

    $env:INGEST_TOKEN = Read-Host "Enter a private sensor-ingestion token"

The token is required for `POST /api/readings`; sensor clients must send it in the `X-Token` header. The resident must also be signed in.

Fresh randomized simulated readings are generated whenever the server starts, replacing earlier simulated readings while preserving any rows with `source='sensor'`. All resident accounts on the same server see the same generated household data. Accounts, sessions, and saved actions are not reset. The demo data covers the latest 75 days, so available calendar dates depend on when the server is started.

The Monthly Report includes a selectable calendar of available daily readings; select a day to see its total and appliance-by-appliance usage.

To use real hardware later, insert rows into `readings` with `source='sensor'`.
