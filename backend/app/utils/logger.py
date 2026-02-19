# backend/app/utils/logger.py
import logging
import sys

# Configure the formatting
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s"


def setup_logger(name: str = "app"):
    logger = logging.getLogger(name)

    # Prevent duplicate handlers if re-imported
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(console_handler)

        # Optional: File Handler (uncomment to save to file)
        # file_handler = logging.FileHandler("app.log")
        # file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        # logger.addHandler(file_handler)

    return logger
