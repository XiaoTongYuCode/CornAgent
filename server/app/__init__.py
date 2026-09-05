"""CornAgent owns dotenv loading through Settings, not provider import side effects."""

import os

os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
