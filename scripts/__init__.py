"""Utility scripts package for Gromozeka.

This package contains standalone CLI scripts and utilities for operating,
debugging, and inspecting the Gromozeka bot. The scripts are designed to
be run from the repository root using the project virtual environment:

    ./venv/bin/python3 scripts/<script_name>.py [flags]

Scripts in this package:
    check_structured_output.py — Probe each configured LLM model for
        structured-output (JSON Schema) support and report which models
        are ready to have ``support_structured_output`` flipped to ``true``
        in the config files.
"""
