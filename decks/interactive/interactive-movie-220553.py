from manim import *

from manim_kit.beats import BeatMixin


class InteractiveMovieScene(BeatMixin, Scene):
    def construct(self):
        self.beat("empty", label="Empty slate")
        # <manim-studio-step id="step_001">
        headline = Text('Second Proposal', font_size=44, color=TEAL)
        caption = Text('Fresh candidate for the live test', font_size=24).next_to(headline, DOWN)
        left_circle = Circle(radius=0.45, color=ORANGE).shift(LEFT * 2.4)
        right_square = Square(side_length=0.9, color=PURPLE).shift(RIGHT * 2.4)
        connector = DashedLine(left_circle.get_right(), right_square.get_left(), color=WHITE)
        self.play(FadeIn(headline, shift=UP * 0.3))
        self.play(Write(caption))
        self.play(Create(left_circle), Create(right_square))
        self.play(Create(connector), left_circle.animate.set_fill(ORANGE, opacity=0.35), right_square.animate.set_fill(PURPLE, opacity=0.35))
        self.wait(0.5)
        self.beat("step_001", label="Second embedded preview proposal")
        # </manim-studio-step>
        self.wait(0.1)
