import logging
import os


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("FRAUD_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )
