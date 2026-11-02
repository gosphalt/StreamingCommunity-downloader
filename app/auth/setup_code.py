"""One-time code that gates the first-run wizard.

/api/auth/setup and /api/auth/skip need no login, so on a panel published
before the wizard is finished anyone could claim it. The code is printed in the
log at start-up, which only whoever runs the panel can read. In memory and
regenerated on every start: the wizard happens once, and a restart before it
completes just prints a new one. Fails closed: no code, no wizard.
"""

import hmac
import logging
import secrets

from app.auth import models

logger = logging.getLogger(__name__)

_code = ""


def issue() -> None:
    """Make a code if the wizard is still pending, and print it."""
    global _code
    if models.setup_done():
        _code = ""
        return
    _code = secrets.token_urlsafe(8)
    logger.warning("Setup code (needed to finish the first-run wizard): %s", _code)


def verify(presented: str) -> bool:
    return bool(_code) and hmac.compare_digest(_code, presented or "")
