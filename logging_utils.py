#!/usr/bin/env python3
"""Logging utilities for au-revoir-gitlab."""

import os
import sys
import time

import colorama

from security import SecurityValidator

# Initialize colorama for cross-platform colored output
colorama.init(autoreset=True)


class Logger:
    """Handles formatted console output with colors and security-aware logging."""

    PROCESS_NAME = "au-revoir-gitlab"

    @classmethod
    def debug(cls, *messages: str) -> None:
        sanitized_messages = [
            SecurityValidator.sanitize_for_logging(msg) for msg in messages
        ]
        cls._write_stdout(colorama.Fore.LIGHTBLACK_EX, *sanitized_messages)

    @classmethod
    def info(cls, *messages: str) -> None:
        sanitized_messages = [
            SecurityValidator.sanitize_for_logging(msg) for msg in messages
        ]
        cls._write_stdout(colorama.Fore.CYAN, *sanitized_messages)

    @classmethod
    def warn(cls, *messages: str) -> None:
        sanitized_messages = [
            SecurityValidator.sanitize_for_logging(msg) for msg in messages
        ]
        cls._write_stdout(colorama.Fore.YELLOW, *sanitized_messages)

    @classmethod
    def error(cls, *messages: str) -> None:
        sanitized_messages = [
            SecurityValidator.sanitize_for_logging(msg) for msg in messages
        ]
        cls._write_stderr(colorama.Fore.RED, *sanitized_messages)

    @classmethod
    def security_event(cls, event_type: str, details: str) -> None:
        """Log security events with appropriate sanitization."""
        sanitized_details = SecurityValidator.sanitize_for_logging(details)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cls._write_stderr(
            colorama.Fore.MAGENTA,
            f"[SECURITY:{event_type}] {timestamp}: {sanitized_details}",
        )

    @classmethod
    def _write_stdout(cls, color: str, *messages: str) -> None:
        sys.stdout.write(cls._format_line(color, *messages) + "\n")

    @classmethod
    def _write_stderr(cls, color: str, *messages: str) -> None:
        sys.stderr.write(cls._format_line(color, *messages) + "\n")

    @classmethod
    def _get_header(cls) -> str:
        return f"[{cls.PROCESS_NAME}:{os.getpid()}]"

    @classmethod
    def _format_line(cls, color: str, *messages: str) -> str:
        header = cls._get_header()
        message = " ".join(str(m) for m in messages)
        return f"{color}{header}{colorama.Style.RESET_ALL} {message}"