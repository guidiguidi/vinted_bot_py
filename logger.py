import logging
import os
import sys
from logging.handlers import RotatingFileHandler

os.makedirs('logs', exist_ok=True)


class ExcludeFilter(logging.Filter):
    def filter(self, record):
        if record.name == 'apscheduler.executors.default' and (
                'Running job' in record.getMessage() or
                'executed successfully' in record.getMessage()):
            return False

        if record.name == 'apscheduler.scheduler' and (
                'Added job' in record.getMessage() or
                'Adding job tentatively' in record.getMessage() or
                'Removed job' in record.getMessage() or
                'Scheduler started' in record.getMessage() or
                'skipped: maximum number of running instances reached' in record.getMessage()):
            return False

        # Filter out httpx HTTP request logs
        if record.name == 'httpx' and 'HTTP Request:' in record.getMessage():
            return False

        return True


def configure_root_logger():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)

    file_handler = RotatingFileHandler(
        'logs/vinted.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    exclude_filter = ExcludeFilter()
    console_handler.addFilter(exclude_filter)
    file_handler.addFilter(exclude_filter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def get_logger(name):
    if not logging.getLogger().handlers:
        configure_root_logger()
    return logging.getLogger(name)
