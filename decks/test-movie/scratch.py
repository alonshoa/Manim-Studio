from manim import *

import math

from manim_kit.beats import BeatMixin


class TestMovieScene(BeatMixin, Scene):
    def construct(self):
        self.beat("empty", label="Empty slate")
        axes = Axes(
            x_range=[-6, 7, 1],
            y_range=[-2, 2.5, 1],
            x_length=10,
            y_length=4.5,
            tips=True,
        )
        self.play(Create(axes))
        self.wait(0.4)
        self.beat("sine", label="Plot sine function")
        sine_curve = axes.plot(
            lambda x: math.sin(x),
            x_range=[-6, 6],
            color=YELLOW,
        )
        self.play(Create(sine_curve))
        self.wait(0.6)
        self.wait(0.1)
