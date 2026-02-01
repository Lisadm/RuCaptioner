"""Utility for handling graceful shutdown and watchdog monitoring."""

import os
import sys
import threading
import logging

logger = logging.getLogger("rucaptioner.utils.shutdown")

def start_stdin_watchdog():
    """Starts a thread that monitors stdin for EOF (closed pipe).
    When Electron closes, the stdin pipe is closed, and this thread will detect it.
    """
    def watchdog():
        logger.info("Stdin watchdog started")
        try:
            # sys.stdin.read(1) blocks until at least one character is available
            # or the pipe is closed (reaching EOF)
            while True:
                data = sys.stdin.read(1)
                if not data:
                    logger.info("Stdin pipe closed (EOF), self-terminating...")
                    # os._exit is used to bypass any Python-level cleanup that might hang
                    os._exit(0)
        except Exception as e:
            logger.error(f"Error in stdin watchdog: {e}")
            os._exit(1)

    thread = threading.Thread(target=watchdog, daemon=True, name="StdinWatchdog")
    thread.start()
    return thread
