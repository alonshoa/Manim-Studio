from manim import *

from manim_kit.beats import BeatMixin


class InteractiveMovieTestScene(BeatMixin, Scene):
    def construct(self):
        self.beat("empty", label="Empty slate")
        # <manim-studio-step id="step_001">
        dot = Dot(color=RED, radius=0.18)
        self.play(FadeIn(dot), run_time=0.4)
        self.play(dot.animate.scale(2), run_time=0.8)
        self.wait(0.3)
        self.beat("step_001", label="Red dot grows 2x")
        # </manim-studio-step>
        self.wait(0.1)
