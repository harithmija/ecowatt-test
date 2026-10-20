# EcoWatt AI

    pip install -r requirements.txt
    set GEMINI_API_KEY=your_key      (optional; Windows. Without it, built-in rules answer)
    streamlit run app.py

Simulated readings are generated on first run into `ecowatt.db`. Delete the file to regenerate.
To use real hardware later, insert rows into `readings` with `source='sensor'`.
