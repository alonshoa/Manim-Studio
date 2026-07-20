from manim import BLUE, Circle, Create, Scene
from manim_kit import DEFAULT_THEME


class SmokeScene(Scene):
    def construct(self):
        circle = Circle(radius=1.0, color=BLUE)
        circle.set_stroke(width=8)
        self.camera.background_color = DEFAULT_THEME.neutral_text_color
        self.play(Create(circle), run_time=0.25)
