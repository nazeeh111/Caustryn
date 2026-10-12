# SPDX-License-Identifier: MIT
"""Locate packaged resources without depending on the working directory."""

from pathlib import Path


def resource_root():
    package = Path(__file__).resolve().parent
    return package / "assets" if (package / "assets").is_dir() else package.parent
