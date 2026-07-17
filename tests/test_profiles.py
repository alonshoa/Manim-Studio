from __future__ import annotations

import unittest

from manim_studio.profiles import get_profile, profile_names


class RenderProfileTests(unittest.TestCase):
    def test_standard_profiles_are_centrally_defined(self) -> None:
        self.assertEqual("-ql", get_profile("draft").quality_flag)
        self.assertEqual("-qm", get_profile("review").quality_flag)
        self.assertEqual("-qh", get_profile("final").quality_flag)

    def test_profile_names_match_standard_profiles(self) -> None:
        self.assertEqual(("draft", "final", "review"), profile_names())

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown render profile"):
            get_profile("preview")


if __name__ == "__main__":
    unittest.main()
