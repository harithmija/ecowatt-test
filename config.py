"""Private settings. Users never see these. For a public repo, set the key as an environment variable instead."""
import os
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GRID_KG_PER_KWH = 0.70  # estimate; verify against the latest official Malaysian grid emission factor
