import json
import logging

logger = logging.getLogger("reme")


def event(name: str, **fields):
    # IDs and counts only; do not log browsing text, captures, or credentials.
    logger.info(json.dumps({"event": name, **fields}))
