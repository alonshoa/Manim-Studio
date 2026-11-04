"""Regression tests for the public research lifecycle boundary."""
from pathlib import Path
from unittest.mock import patch

from manim_studio import research_lifecycle as lifecycle


def test_start_does_not_claim_capture_when_disabled(tmp_path):
    result = lifecycle.start(tmp_path, title='Pilot', topic='Deck')
    assert result['status'] == 'ACTION_REQUIRED'
    assert result['reason'] == 'capture_disabled'


def test_start_requires_observed_hook_before_claiming_ready(tmp_path):
    from manim_studio.research import ResearchLog
    ResearchLog(tmp_path).configure(True, managed=True)
    result = lifecycle.start(tmp_path, title='Pilot', topic='Deck')
    assert result['status'] == 'ACTION_REQUIRED'
    assert result['capture_verified'] is False
    assert result['session_id']
    repeated = lifecycle.start(tmp_path, title='Pilot', topic='Deck')
    assert repeated['session_id'] == result['session_id']


def test_finish_without_active_session_does_not_create_one(tmp_path):
    result = lifecycle.finish(tmp_path)
    assert result['status'] == 'ACTION_REQUIRED'
    assert result['reason'] == 'expected_one_active_session'


def test_cli_exposes_research_lifecycle_commands():
    from manim_studio.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(['research', 'start', '--json']).research_command == 'start'
    assert parser.parse_args(['research', 'finish', '--json']).research_command == 'finish'
