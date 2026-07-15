from manim import *
from manim_slides import Slide


class VectorsABtoV(Slide):
    VECTOR_A = (2, 2)
    VECTOR_B = (-1, 1)
    VECTOR_V = (1, 3)
    HEBREW_FONT = "DejaVu Sans"

    def construct(self):
        title = Text("וקטורים", font=self.HEBREW_FONT).scale(1.2)
        self.play(FadeIn(title))
        self.wait(0.6)
        self.play(FadeOut(title))
        self.next_slide()

        axes = Axes(
            x_range=[-3, 6, 1],
            y_range=[-2, 6, 1],
            x_length=7,
            y_length=5,
            axis_config={"include_tip": True, "include_numbers": True},
            tips=True,
        ).to_edge(LEFT, buff=0.5)
        self.play(Create(axes))
        self.next_slide()

        subtitle = Text(
            "פירוק לרכיבים: a ו-b",
            font=self.HEBREW_FONT,
        ).scale(0.45)
        subtitle.next_to(axes, UP, buff=0.2)
        self.play(FadeIn(subtitle))

        a_group = self._make_vector(axes, self.VECTOR_A, BLUE, r"\vec a")
        b_group = self._make_vector(axes, self.VECTOR_B, GREEN, r"\vec b")
        self.play(GrowArrow(a_group[0]), FadeIn(a_group[1:]))
        self.play(GrowArrow(b_group[0]), FadeIn(b_group[1:]))
        self.next_slide()

        right_col = self._make_algebra_panel()
        right_col.to_edge(RIGHT, buff=0.6).shift(UP * 0.8)
        if right_col.width > 4.6:
            right_col.set_width(4.6)
        box = SurroundingRectangle(
            right_col,
            color=GREY_B,
            stroke_opacity=0.6,
            corner_radius=0.1,
            buff=0.25,
        )
        self.play(FadeIn(box), Write(right_col[0]))
        self.next_slide()

        a_tip = axes.c2p(*self.VECTOR_A)
        shift_vec = a_tip - axes.c2p(0, 0)
        move_caption = Text(
            "חיבור קצה-לקצה: מזיזים את b לראש של a",
            font=self.HEBREW_FONT,
        ).scale(0.4)
        move_caption.next_to(axes, DOWN, buff=0.2)
        self.play(FadeIn(move_caption))
        self.play(b_group.animate.shift(shift_vec), run_time=1.0)
        self.next_slide()

        v_group = self._make_vector(axes, self.VECTOR_V, YELLOW, r"\vec v")
        v_group[0].set_stroke(width=8, opacity=0.65)
        self.play(Flash(axes.c2p(*self.VECTOR_V), color=YELLOW, flash_radius=0.6))
        self.play(Create(v_group[0]), FadeIn(v_group[1:]))
        self.play(Write(right_col[1:]))
        self.next_slide()

        self.next_slide(loop=True)
        self.play(Indicate(v_group[0], color=YELLOW), run_time=1.2)

    def _make_vector(self, axes, vector, color, label_text):
        arrow = Arrow(
            axes.c2p(0, 0),
            axes.c2p(*vector),
            buff=0,
            max_tip_length_to_length_ratio=0.12,
            stroke_width=6,
            color=color,
        )
        dot = Dot(axes.c2p(*vector), color=color)
        label = MathTex(label_text).scale(0.7).set_color(color)
        label.next_to(dot, UR, buff=0.15)
        return VGroup(arrow, dot, label)

    def _make_algebra_panel(self):
        vectors = VGroup(
            MathTex(r"\vec a=\begin{pmatrix}2\\2\end{pmatrix}")
            .scale(0.9)
            .set_color(BLUE),
            MathTex(r"\vec b=\begin{pmatrix}-1\\1\end{pmatrix}")
            .scale(0.9)
            .set_color(GREEN),
        ).arrange(RIGHT, buff=0.8, aligned_edge=DOWN)

        sum_eq = MathTex(r"\vec a+\vec b=\vec v").scale(0.9)
        sum_eq.set_color_by_tex(r"\vec a", BLUE)
        sum_eq.set_color_by_tex(r"\vec b", GREEN)
        sum_eq.set_color_by_tex(r"\vec v", YELLOW)

        sum_num = MathTex(
            r"\begin{pmatrix}2\\2\end{pmatrix}"
            r"+"
            r"\begin{pmatrix}-1\\1\end{pmatrix}"
            r"="
            r"\begin{pmatrix}1\\3\end{pmatrix}"
        ).scale(0.9)
        result = MathTex(r"\vec v=\begin{pmatrix}1\\3\end{pmatrix}")
        result.scale(0.9).set_color(YELLOW)

        return VGroup(vectors, sum_eq, sum_num, result).arrange(
            DOWN,
            aligned_edge=LEFT,
            buff=0.28,
        )
