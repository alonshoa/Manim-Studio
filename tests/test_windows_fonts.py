import sys
import types
import unittest
from unittest.mock import patch
from manim_studio.cli import _check_hebrew_fonts


class WindowsFontsTests(unittest.TestCase):
    def test_windows_checks_the_actual_manim_font_backend_without_fontconfig(self):
        backend = types.SimpleNamespace(list_fonts=lambda: ['Arial', 'DejaVu Sans'])
        with patch('manim_studio.cli.sys.platform', 'win32'), patch.dict(sys.modules, manimpango=backend):
            result = _check_hebrew_fonts()
        self.assertTrue(result.ok)
        self.assertEqual(result.detail, 'DejaVu Sans')

    def test_windows_reports_missing_documented_font(self):
        backend = types.SimpleNamespace(list_fonts=lambda: ['Arial'])
        with patch('manim_studio.cli.sys.platform', 'win32'), patch.dict(sys.modules, manimpango=backend):
            result = _check_hebrew_fonts()
        self.assertFalse(result.ok)
        self.assertIn('DejaVu', result.fix)
