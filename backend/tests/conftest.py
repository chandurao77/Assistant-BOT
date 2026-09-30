"""Shared test fixtures and environment setup."""
import os

# Ensure tests run in 'test' environment — prevents production-only validators
# from blocking test collection (e.g., JWT secret requirement).
os.environ.setdefault("ENVIRONMENT", "test")
