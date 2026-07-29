from manim import *

from manim_kit import BeatMixin


class VisualRecursionTree(BeatMixin, MovingCameraScene):
    BACKGROUND = "#F7F6F0"
    TEXT = "#172026"
    MUTED = "#A9B0B8"
    ROOT = "#2E5EAA"
    RECURSIVE = "#209D8F"
    BASE = "#36A166"
    RETURN = "#D69E2E"
    ALERT = "#D64545"

    NODE_HEIGHT = 0.55
    LEVEL_YS = (2.35, 0.85, -0.65, -2.15)
    LEVEL_SPANS = (0.0, 5.0, 8.2, 11.0)
    LEVEL_WIDTHS = (2.2, 1.8, 1.45, 1.05)

    def construct(self):
        self.camera.background_color = self.BACKGROUND

        title = Text("Recursion", font_size=42, color=self.TEXT)
        title.to_edge(UP, buff=0.25)

        nodes = {}
        edges = {}
        for level in range(4):
            for index in range(2**level):
                label = self._label_for(level)
                fill = self.BASE if level == 3 else self.RECURSIVE
                if level == 0:
                    fill = self.ROOT
                node = self._make_node(
                    label,
                    self._node_point(level, index),
                    width=self.LEVEL_WIDTHS[level],
                    fill=fill,
                    font_size=24 if level < 3 else 19,
                )
                nodes[(level, index)] = node

        for level in range(1, 4):
            for index in range(2**level):
                parent_key = (level - 1, index // 2)
                child_key = (level, index)
                edges[child_key] = self._make_edge(nodes[parent_key], nodes[child_key])

        self.beat("intro_problem", label="One problem")
        root = nodes[(0, 0)]
        intro_text = Text(
            "A problem can contain smaller versions of itself.",
            font_size=24,
            color=self.TEXT,
        ).next_to(root, DOWN, buff=0.45)
        self.play(Write(title), FadeIn(root, shift=DOWN * 0.2))
        self.play(root.animate.scale(1.08), rate_func=there_and_back, run_time=0.8)
        self.play(FadeIn(intro_text, shift=UP * 0.15))
        self.wait(0.4)

        self.beat("reveal_rule", label="Split by the same rule")
        first_layer = VGroup(nodes[(1, 0)], nodes[(1, 1)])
        first_edges = VGroup(edges[(1, 0)], edges[(1, 1)])
        rule_tag = self._small_tag("same rule", self.RECURSIVE).next_to(root, RIGHT, buff=0.25)
        self.play(FadeOut(intro_text), FadeIn(rule_tag, shift=LEFT * 0.15))
        self.play(
            LaggedStart(Create(first_edges), FadeIn(first_layer, shift=DOWN * 0.25), lag_ratio=0.25),
            run_time=1.4,
        )
        self.wait(0.4)

        self.beat("repeat_structure", label="Repeat the structure")
        second_layer = VGroup(*[nodes[(2, index)] for index in range(4)])
        second_edges = VGroup(*[edges[(2, index)] for index in range(4)])
        repeat_label = Text("Each call repeats the same structure.", font_size=23, color=self.TEXT)
        repeat_label.next_to(second_layer, DOWN, buff=0.25)
        self.play(
            root[0].animate.set_stroke(self.MUTED, width=1.5),
            first_layer.animate.set_opacity(0.78),
        )
        self.play(
            LaggedStart(Create(second_edges), FadeIn(second_layer, shift=DOWN * 0.2), lag_ratio=0.2),
            FadeIn(repeat_label, shift=UP * 0.1),
            run_time=1.8,
        )
        self.wait(0.4)

        self.beat("zoom_inside", label="A recursive call is the same world")
        focus = nodes[(2, 1)]
        frame = self.camera.frame
        frame.save_state()
        focus_box = SurroundingRectangle(focus, color=self.RETURN, buff=0.08, stroke_width=4)
        inside_label = Text("same rule again", font_size=20, color=self.TEXT)
        inside_label.next_to(focus, UP, buff=0.25)
        self.play(FadeOut(repeat_label), Create(focus_box))
        self.play(frame.animate.set(width=5.0).move_to(focus.get_center() + DOWN * 0.25), run_time=1.4)
        preview_children = VGroup(nodes[(3, 2)].copy(), nodes[(3, 3)].copy())
        preview_edges = VGroup(edges[(3, 2)].copy(), edges[(3, 3)].copy())
        preview_children.set_color(self.RECURSIVE)
        self.play(Write(inside_label), Create(preview_edges), FadeIn(preview_children), run_time=1.2)
        self.wait(0.4)
        self.play(
            Restore(frame),
            FadeOut(focus_box),
            FadeOut(inside_label),
            FadeOut(preview_edges),
            FadeOut(preview_children),
            run_time=1.2,
        )

        self.beat("base_case", label="Stop condition")
        base_nodes = VGroup(*[nodes[(3, index)] for index in range(8)])
        base_edges = VGroup(*[edges[(3, index)] for index in range(8)])
        stop_line = Line(LEFT * 0.32, RIGHT * 0.32, color=self.ALERT, stroke_width=6)
        stop_line.next_to(base_nodes[3], DOWN, buff=0.18)
        stop_copy = stop_line.copy().next_to(base_nodes[4], DOWN, buff=0.18)
        base_label = Text("base case: stop splitting", font_size=24, color=self.TEXT)
        base_label.next_to(base_nodes, DOWN, buff=0.45)
        self.play(
            LaggedStart(Create(base_edges), FadeIn(base_nodes, shift=DOWN * 0.2), lag_ratio=0.1),
            run_time=2.0,
        )
        self.play(
            base_nodes.animate.set_opacity(1),
            FadeIn(VGroup(stop_line, stop_copy), shift=UP * 0.1),
            Write(base_label),
        )
        self.wait(0.5)

        self.beat("return_values", label="Answers flow back up")
        self.play(FadeOut(base_label), FadeOut(stop_line), FadeOut(stop_copy))
        return_label = Text("answers return upward", font_size=25, color=self.TEXT)
        return_label.next_to(title, DOWN, buff=0.15)
        self.play(FadeIn(return_label, shift=DOWN * 0.1))
        self._return_flow(nodes, source_level=3, target_level=2)
        self._highlight_level(nodes, 2)
        self._return_flow(nodes, source_level=2, target_level=1)
        self._highlight_level(nodes, 1)
        self._return_flow(nodes, source_level=1, target_level=0)
        self._highlight_level(nodes, 0)
        self.wait(0.4)

        self.beat("final_summary", label="Recursive recipe")
        tree = VGroup(
            *nodes.values(),
            *edges.values(),
            rule_tag,
            title,
            return_label,
        )
        summary_title = Text("Recursive recipe", font_size=31, color=self.TEXT)
        summary_lines = VGroup(
            Text("1. same rule", font_size=25, color=self.TEXT),
            Text("2. smaller input", font_size=25, color=self.TEXT),
            Text("3. base case", font_size=25, color=self.TEXT),
            Text("4. return upward", font_size=25, color=self.TEXT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.28)
        summary = VGroup(summary_title, summary_lines).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        summary.to_edge(RIGHT, buff=0.65).shift(DOWN * 0.1)
        self.play(tree.animate.scale(0.74).to_edge(LEFT, buff=0.35), run_time=1.2)
        self.play(Write(summary_title), LaggedStartMap(FadeIn, summary_lines, shift=RIGHT * 0.15, lag_ratio=0.18))
        self.wait(2.0)

    def _label_for(self, level):
        if level == 0:
            return "solve(n)"
        if level == 3:
            return "base"
        return f"solve(n-{level})"

    def _node_point(self, level, index):
        count = 2**level
        span = self.LEVEL_SPANS[level]
        x = 0 if count == 1 else -span / 2 + index * span / (count - 1)
        return np.array([x, self.LEVEL_YS[level], 0])

    def _make_node(self, label, center, width, fill, font_size):
        rect = RoundedRectangle(
            corner_radius=0.11,
            height=self.NODE_HEIGHT,
            width=width,
            stroke_color=self.TEXT,
            stroke_width=2,
        )
        rect.set_fill(fill, opacity=0.92)
        rect.move_to(center)
        text = Text(label, font_size=font_size, color=WHITE)
        text.move_to(center)
        return VGroup(rect, text)

    def _make_edge(self, parent, child):
        start = parent.get_bottom() + DOWN * 0.04
        end = child.get_top() + UP * 0.04
        return Arrow(
            start,
            end,
            buff=0.05,
            stroke_width=2.3,
            color=self.MUTED,
            max_tip_length_to_length_ratio=0.08,
        )

    def _small_tag(self, label, color):
        tag = RoundedRectangle(
            corner_radius=0.1,
            height=0.36,
            width=1.25,
            stroke_color=color,
            stroke_width=2,
        )
        tag.set_fill(self.BACKGROUND, opacity=1)
        text = Text(label, font_size=16, color=color)
        text.move_to(tag)
        return VGroup(tag, text)

    def _return_flow(self, nodes, source_level, target_level):
        animations = []
        for source_index in range(2**source_level):
            target_index = source_index // 2 if target_level == source_level - 1 else source_index
            dot = Dot(color=self.RETURN, radius=0.06)
            start = nodes[(source_level, source_index)].get_center()
            end = nodes[(target_level, target_index)].get_center()
            dot.move_to(start)
            self.add(dot)
            animations.append(MoveAlongPath(dot, Line(start, end), run_time=0.85))
            animations.append(FadeOut(dot, run_time=0.15))
        self.play(AnimationGroup(*animations, lag_ratio=0.04), run_time=1.2)

    def _highlight_level(self, nodes, level):
        self.play(
            *[
                nodes[(level, index)][0].animate.set_fill(self.RETURN, opacity=0.95)
                for index in range(2**level)
            ],
            run_time=0.35,
        )
