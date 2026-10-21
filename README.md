# EcoWatt AI

    pip install -r requirements.txt
    $env:GEMINI_API_KEY = Read-Host "Enter your Gemini API key"
    python -m uvicorn server:app --reload

The API key is optional. Without it, the built-in rules answer. In PowerShell, set the environment variable in the same terminal before starting Uvicorn.

Simulated readings are generated on first run into `ecowatt.db`. Delete the file to regenerate.
To use real hardware later, insert rows into `readings` with `source='sensor'`.
