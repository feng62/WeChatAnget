# -*- coding: utf-8 -*-
"""Path utilities for locating project root, data, static, and config directories."""

import os

# src/core/path_utils.py -> src/core -> src -> PROJECT_ROOT
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CORE_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
MEDIA_CACHE_DIR = os.path.join(PROJECT_ROOT, "media-cache")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
