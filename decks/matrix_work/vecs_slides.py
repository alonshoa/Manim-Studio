from manim import *

from manim_kit import DEFAULT_THEME, HebrewSlide, explanation_panel, hebrew_text


class VectorsABtoV(HebrewSlide):
    VECTOR_A = (2, 2)
    VECTOR_B = (-1, 1)
    VECTOR_V = (1, 3)

    def construct(self):
        self.beat("intro", label="Title")
        title = hebrew_text("וקטורים", scale=DEFAULT_THEME.title_scale)
        self.play(FadeIn(title))
        self.wait(0.6)
        self.play(FadeOut(title))
        self.beat("axes", label="Coordinate plane")

        axes = Axes(
            x_range=[-3, 6, 1],
            y_range=[-2, 6, 1],
            x_length=7,
            y_length=5,
            axis_config={"include_tip": True, "include_numbers": True},
            tips=True,
        ).to_edge(LEFT, buff=0.5)
        self.play(Create(axes))
        self.beat("components", label="Show vector components")

        subtitle = hebrew_text(
            "פירוק לרכיבים: a ו-b",
            scale=DEFAULT_THEME.subtitle_scale,
        )
        subtitle.next_to(axes, UP, buff=0.2)
        self.play(FadeIn(subtitle))

        a_group = self._make_vector(axes, self.VECTOR_A, BLUE, r"\vec a")
        b_group = self._make_vector(axes, self.VECTOR_B, GREEN, r"\vec b")
        self.play(GrowArrow(a_group[0]), FadeIn(a_group[1:]))
        self.play(GrowArrow(b_group[0]), FadeIn(b_group[1:]))
        self.beat("algebra_panel", label="Introduce algebra panel")

        right_col = self._make_algebra_panel()
        panel = explanation_panel(right_col)
        panel.to_edge(RIGHT, buff=0.6).shift(UP * 0.8)
        box = panel[0]
        self.play(FadeIn(box), Write(right_col[0]))
        self.beat("tail_to_head", label="Move b to the head of a")

        a_tip = axes.c2p(*self.VECTOR_A)
        shift_vec = a_tip - axes.c2p(0, 0)
        move_caption = hebrew_text(
            "חיבור קצה-לקצה: מזיזים את b לראש של a",
            scale=DEFAULT_THEME.caption_scale,
        )
        move_caption.next_to(axes, DOWN, buff=0.2)
        self.play(FadeIn(move_caption))
        self.play(b_group.animate.shift(shift_vec), run_time=1.0)
        self.beat("resultant", label="Reveal resultant vector")

        v_group = self._make_vector(axes, self.VECTOR_V, YELLOW, r"\vec v")
        v_group[0].set_stroke(width=8, opacity=0.65)
        self.play(Flash(axes.c2p(*self.VECTOR_V), color=YELLOW, flash_radius=0.6))
        self.play(Create(v_group[0]), FadeIn(v_group[1:]))
        self.play(Write(right_col[1:]))

        self.beat("emphasis_loop", label="Emphasize resultant", loop=True)
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
