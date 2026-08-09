from manim import *

from manim_kit.beats import BeatMixin


class InteractiveVsTestScene(BeatMixin, Scene):
    def construct(self):
        self.beat("empty", label="Empty slate")
        self.wait(0.1)
