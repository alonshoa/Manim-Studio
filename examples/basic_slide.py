from manim import *
from manim_slides import Slide


class BasicSlide(Slide):
    def construct(self):
        title = Text("Manim Studio", font="DejaVu Sans")
        subtitle = Text("Slide smoke test", font="DejaVu Sans").scale(0.6)
        subtitle.next_to(title, DOWN)

        self.play(FadeIn(title))
        self.next_slide()
        self.play(FadeIn(subtitle))
        self.next_slide()
        self.play(FadeOut(title), FadeOut(subtitle))
