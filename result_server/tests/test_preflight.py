"""Tests for production preflight secret validation."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.preflight import validate_ingest_keys, validate_production_config


def test_rejects_short_ingest_keys():
    errors = validate_ingest_keys({"short-key": "runner-a"})

    assert any("at least 32 characters" in error for error in errors)


def test_rejects_known_insecure_ingest_defaults():
    errors = validate_ingest_keys({"dev-api-key": "runner-a"})

    assert any("known-insecure default" in error for error in errors)


def test_accepts_parallel_rotation_keys_for_same_runner():
    old_key = "old-runner-key-01234567890123456789"
    new_key = "new-runner-key-01234567890123456789"

    assert validate_ingest_keys({old_key: "runner-a", new_key: "runner-a"}) == []


def test_rejects_short_flask_secret_key():
    env = {"FLASK_SECRET_KEY": "short"}
    errors = validate_production_config(env, {"runner-key-012345678901234567890": "runner-a"})

    assert any("FLASK_SECRET_KEY must be at least 32 characters" in error for error in errors)


def test_accepts_strong_production_config():
    env = {"FLASK_SECRET_KEY": "flask-secret-012345678901234567890"}
    ingest_keys = {"runner-key-012345678901234567890": "runner-a"}

    assert validate_production_config(env, ingest_keys) == []
