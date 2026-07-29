from manim import *

from manim_kit import HebrewSlide, StudioSlide, hebrew_text


class CountBottlesRecursion(StudioSlide):
    BOTTLE_COUNT = 4

    BACKGROUND = "#F7F6F0"
    TEXT = "#172026"
    MUTED = "#A9B0B8"
    BOX = "#5A4634"
    BOX_FILL = "#E9D9B8"
    BOTTLE = "#2E5EAA"
    BOTTLE_LIGHT = "#80B6D9"
    BASE = "#36A166"
    RETURN = "#D69E2E"
    MACHINE = "#209D8F"
    ALERT = "#D64545"

    def construct(self):
        self.camera.background_color = ManimColor(self.BACKGROUND)

        self.beat("intro_problem", label="Concrete counting problem")
        title = Text("Counting with recursion", font_size=42, color=self.TEXT)
        title.to_edge(UP, buff=0.28)
        box, bottles = self._make_box(self.BOTTLE_COUNT, "box")
        box.to_edge(LEFT, buff=0.85).shift(DOWN * 0.25)
        lid = self._make_lid(box)
        question = Text("How many bottles?", font_size=29, color=self.TEXT)
        question.next_to(box, DOWN, buff=0.35)
        cue = Text(
            "We want one rule that counts any box.",
            font_size=23,
            color=self.TEXT,
        ).to_edge(DOWN, buff=0.35)

        self.play(Write(title), FadeIn(VGroup(box[0], box[2]), shift=DOWN * 0.15), FadeIn(lid))
        self.play(
            lid.animate.shift(UP * 0.35 + RIGHT * 0.15).rotate(-14 * DEGREES),
            LaggedStartMap(FadeIn, bottles, shift=UP * 0.12, lag_ratio=0.12),
            run_time=1.4,
        )
        self.play(Write(question), FadeIn(cue, shift=UP * 0.12))
        self.wait(0.5)

        self.beat("base_case", label="Empty box returns zero")
        self._fade_out_all()
        title = self._scene_title("Base case")
        empty_box, _ = self._make_box(0, "empty box")
        empty_box.to_edge(LEFT, buff=0.95).shift(DOWN * 0.2)
        machine = self._make_machine("count(empty box)")
        machine.move_to(RIGHT * 0.8 + DOWN * 0.1)
        output = self._result_token("0", self.BASE)
        output.next_to(machine, RIGHT, buff=0.75)
        base_label = self._tag("base case", self.BASE)
        base_label.next_to(empty_box, UP, buff=0.25)
        formula = Text("count(empty box) = 0", font_size=28, color=self.TEXT)
        formula.to_edge(DOWN, buff=0.42)
        input_arrow = Arrow(
            empty_box.get_right() + RIGHT * 0.1,
            machine.get_left() + LEFT * 0.1,
            buff=0.1,
            color=self.MUTED,
            stroke_width=3,
        )

        self.play(Write(title), FadeIn(empty_box), FadeIn(machine))
        self.play(Create(SurroundingRectangle(empty_box, color=self.BASE, buff=0.08)))
        self.play(FadeIn(base_label, shift=DOWN * 0.1), Create(input_arrow))
        box_copy = empty_box.copy()
        self.add(box_copy)
        self.play(box_copy.animate.scale(0.55).move_to(machine.get_center()), run_time=1.0)
        self.play(FadeOut(box_copy), machine.animate.set_fill(self.MACHINE, opacity=0.95))
        self.play(FadeIn(output, shift=RIGHT * 0.15), Write(formula))
        self.wait(0.5)

        self.beat("recursive_case_rule", label="Take one bottle")
        self._fade_out_all()
        title = self._scene_title("Recursive case")
        box, bottles = self._make_box(self.BOTTLE_COUNT, "box")
        box.to_edge(LEFT, buff=0.85).shift(DOWN * 0.25)
        selected = bottles[-1]
        rest_box, _ = self._make_box(self.BOTTLE_COUNT - 1, "rest of box")
        rest_box.move_to(box)
        one_label = self._tag("+ 1", self.RETURN)
        one_label.move_to(RIGHT * 1.1 + UP * 0.65)
        rule = Text("count(box) = 1 + count(rest)", font_size=27, color=self.TEXT)
        rule.to_edge(DOWN, buff=0.42)
        recursive_tag = self._tag("recursive case", self.RETURN)
        recursive_tag.next_to(box, UP, buff=0.25)

        self.play(Write(title), FadeIn(box))
        self.play(FadeIn(recursive_tag, shift=DOWN * 0.1), Indicate(selected, color=self.RETURN))
        bottle_copy = selected.copy()
        self.add(bottle_copy)
        self.play(
            bottle_copy.animate.move_to(one_label.get_center() + LEFT * 0.72).scale(1.08),
            selected.animate.set_opacity(0.16),
            run_time=1.0,
        )
        self.play(Transform(box, rest_box), FadeIn(one_label, shift=LEFT * 0.15))
        self.play(Write(rule))
        self.wait(0.5)

        self.beat("send_rest_back", label="Same question, smaller box")
        machine = self._make_machine("count(box)")
        machine.move_to(RIGHT * 1.0 + DOWN * 0.05)
        same_label = Text("same question, smaller box", font_size=24, color=self.TEXT)
        same_label.next_to(machine, UP, buff=0.35)
        rest_arrow = Arrow(
            box.get_right() + RIGHT * 0.1,
            machine.get_left() + LEFT * 0.12,
            buff=0.1,
            color=self.MUTED,
            stroke_width=3,
        )
        rest_call = Text("count(rest)", font_size=26, color=self.MACHINE)
        rest_call.next_to(machine, DOWN, buff=0.22)

        self.play(FadeIn(machine, shift=LEFT * 0.15), FadeIn(same_label, shift=DOWN * 0.12))
        self.play(Create(rest_arrow), run_time=0.7)
        rest_copy = box.copy()
        self.add(rest_copy)
        self.play(rest_copy.animate.scale(0.52).move_to(machine.get_center()), run_time=1.1)
        self.play(
            FadeOut(rest_copy),
            Transform(machine[1], Text("count(rest)", font_size=25, color=WHITE).move_to(machine[1])),
            FadeIn(rest_call, shift=UP * 0.1),
        )
        self.wait(0.6)

        self.beat("unwind_answer", label="Answers return upward")
        self._fade_out_all()
        title = self._scene_title("Answers return")
        call_rows = self._make_call_rows(self.BOTTLE_COUNT)
        call_rows.to_edge(LEFT, buff=0.85).shift(DOWN * 0.15)
        base_highlight = SurroundingRectangle(call_rows[-1], color=self.BASE, buff=0.08)
        return_label = Text(
            "Each waiting bottle adds one.",
            font_size=25,
            color=self.TEXT,
        ).next_to(title, DOWN, buff=0.25)

        self.play(Write(title), FadeIn(call_rows, shift=DOWN * 0.12))
        self.play(FadeIn(return_label, shift=DOWN * 0.1), Create(base_highlight))
        previous_token = None
        for index, value in enumerate(range(0, self.BOTTLE_COUNT + 1)):
            row = call_rows[self.BOTTLE_COUNT - value]
            if value == 0:
                token = self._result_token("0", self.BASE)
            else:
                token = self._result_token(f"1 + {value - 1} = {value}", self.RETURN)
            token.next_to(row, RIGHT, buff=0.75)
            if previous_token is not None:
                arrow = Arrow(
                    previous_token.get_top() + UP * 0.04,
                    token.get_bottom() + DOWN * 0.04,
                    buff=0.08,
                    color=self.RETURN,
                    stroke_width=2.5,
                    max_tip_length_to_length_ratio=0.08,
                )
                self.play(Create(arrow), run_time=0.35)
            self.play(FadeIn(token, shift=RIGHT * 0.15), Indicate(row, color=self.RETURN), run_time=0.75)
            previous_token = token
        final = self._result_token(str(self.BOTTLE_COUNT), self.RETURN)
        final.scale(1.12)
        final.to_edge(RIGHT, buff=0.75).shift(UP * 0.4)
        final_label = Text("final count", font_size=21, color=self.TEXT)
        final_label.next_to(final, UP, buff=0.18)
        self.play(FadeIn(final_label), TransformFromCopy(previous_token, final))
        self.wait(0.8)

        self.beat("final_recipe", label="Two recursive rules")
        self._fade_out_all()
        title = self._scene_title("Recursive recipe")
        summary_box, summary_bottles = self._make_box(2, "box")
        summary_box.to_edge(LEFT, buff=0.9).shift(DOWN * 0.2)
        one = summary_bottles[-1].copy().set_color(self.RETURN)
        one.move_to(LEFT * 0.2 + UP * 0.65)
        rest, _ = self._make_box(1, "rest")
        rest.scale(0.72).move_to(LEFT * 0.2 + DOWN * 0.55)
        split_arrow = Arrow(
            summary_box.get_right() + RIGHT * 0.05,
            rest.get_left() + LEFT * 0.05,
            buff=0.08,
            color=self.MUTED,
            stroke_width=2.5,
        )
        rules = VGroup(
            self._rule_line("empty box", "0", self.BASE),
            self._rule_line("not empty", "1 + count(rest)", self.RETURN),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.38)
        rules.to_edge(RIGHT, buff=0.75).shift(DOWN * 0.05)
        takeaway = Text(
            "Base case + same question on a smaller input.",
            font_size=24,
            color=self.TEXT,
        ).to_edge(DOWN, buff=0.38)

        self.play(Write(title), FadeIn(summary_box))
        self.play(
            TransformFromCopy(summary_bottles[-1], one),
            Create(split_arrow),
            FadeIn(rest, shift=RIGHT * 0.12),
        )
        self.play(LaggedStartMap(FadeIn, rules, shift=LEFT * 0.12, lag_ratio=0.2))
        self.play(Write(takeaway))
        self.wait(1.2)

    def _scene_title(self, text):
        title = Text(text, font_size=39, color=self.TEXT)
        title.to_edge(UP, buff=0.28)
        return title

    def _make_box(self, bottle_count, label):
        shell = RoundedRectangle(
            corner_radius=0.08,
            height=1.75,
            width=3.0,
            stroke_color=self.BOX,
            stroke_width=4,
        )
        shell.set_fill(self.BOX_FILL, opacity=0.45)
        label_text = Text(label, font_size=22, color=self.TEXT)
        label_text.next_to(shell, DOWN, buff=0.14)

        bottles = VGroup()
        if bottle_count:
            spacing = 0.42
            start_x = -spacing * (bottle_count - 1) / 2
            for index in range(bottle_count):
                bottle = self._make_bottle()
                bottle.move_to(shell.get_center() + RIGHT * (start_x + index * spacing) + DOWN * 0.02)
                bottles.add(bottle)

        group = VGroup(shell, bottles, label_text)
        return group, bottles

    def _make_lid(self, box):
        shell = box[0]
        lid = RoundedRectangle(
            corner_radius=0.06,
            height=0.28,
            width=shell.width + 0.16,
            stroke_color=self.BOX,
            stroke_width=3,
        )
        lid.set_fill("#D0B07A", opacity=0.95)
        lid.move_to(shell.get_top() + DOWN * 0.03)
        return lid

    def _make_bottle(self):
        body = RoundedRectangle(
            corner_radius=0.08,
            height=0.82,
            width=0.28,
            stroke_color=self.TEXT,
            stroke_width=1.3,
        )
        body.set_fill(self.BOTTLE_LIGHT, opacity=0.95)
        neck = RoundedRectangle(
            corner_radius=0.04,
            height=0.28,
            width=0.16,
            stroke_color=self.TEXT,
            stroke_width=1.1,
        )
        neck.set_fill(self.BOTTLE, opacity=0.95)
        neck.next_to(body, UP, buff=-0.03)
        cap = Rectangle(
            height=0.07,
            width=0.2,
            stroke_color=self.TEXT,
            stroke_width=1.0,
        )
        cap.set_fill(self.RETURN, opacity=0.95)
        cap.next_to(neck, UP, buff=-0.01)
        shine = Line(LEFT * 0.04, RIGHT * 0.04, color=WHITE, stroke_width=2)
        shine.rotate(PI / 2)
        shine.move_to(body.get_center() + LEFT * 0.07 + UP * 0.12)
        return VGroup(body, neck, cap, shine)

    def _make_machine(self, label):
        body = RoundedRectangle(
            corner_radius=0.12,
            height=1.15,
            width=2.45,
            stroke_color=self.TEXT,
            stroke_width=2.5,
        )
        body.set_fill(self.MACHINE, opacity=0.88)
        text = Text(label, font_size=25, color=WHITE)
        text.move_to(body)
        gear = Circle(radius=0.12, color=WHITE, stroke_width=2)
        gear.move_to(body.get_corner(UR) + LEFT * 0.27 + DOWN * 0.23)
        return VGroup(body, text, gear)

    def _make_call_rows(self, max_count):
        rows = VGroup()
        for count in range(max_count, -1, -1):
            if count == 0:
                label = "count(empty box)"
            elif count == 1:
                label = "count(1 bottle)"
            else:
                label = f"count({count} bottles)"
            row = VGroup(
                RoundedRectangle(
                    corner_radius=0.08,
                    height=0.48,
                    width=2.65,
                    stroke_color=self.MUTED,
                    stroke_width=1.8,
                ),
                Text(label, font_size=21, color=self.TEXT),
            )
            row[1].move_to(row[0])
            rows.add(row)
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.17)
        return rows

    def _result_token(self, label, color):
        box = RoundedRectangle(
            corner_radius=0.09,
            height=0.52,
            width=max(0.92, 0.22 * len(label) + 0.48),
            stroke_color=color,
            stroke_width=2.3,
        )
        box.set_fill(self.BACKGROUND, opacity=1)
        text = Text(label, font_size=24, color=color)
        text.move_to(box)
        return VGroup(box, text)

    def _tag(self, label, color):
        tag = RoundedRectangle(
            corner_radius=0.09,
            height=0.38,
            width=max(1.05, 0.16 * len(label) + 0.42),
            stroke_color=color,
            stroke_width=2,
        )
        tag.set_fill(self.BACKGROUND, opacity=1)
        text = Text(label, font_size=18, color=color)
        text.move_to(tag)
        return VGroup(tag, text)

    def _rule_line(self, condition, result, color):
        condition_text = Text(condition, font_size=25, color=self.TEXT)
        arrow = Text("->", font_size=25, color=self.MUTED)
        result_text = Text(result, font_size=25, color=color)
        return VGroup(condition_text, arrow, result_text).arrange(RIGHT, buff=0.28)

    def _fade_out_all(self):
        if self.mobjects:
            self.play(*[FadeOut(mobject) for mobject in self.mobjects], run_time=0.45)


class HebrewCountBottlesRecursion(CountBottlesRecursion, HebrewSlide):
    def construct(self):
        self.camera.background_color = ManimColor(self.BACKGROUND)

        self.beat("intro_problem", label="בעיית ספירה מוחשית")
        title = self._he_text("ספירה עם רקורסיה", font_size=42, color=self.TEXT)
        title.to_edge(UP, buff=0.28)
        box, bottles = self._make_box(self.BOTTLE_COUNT, "קופסה")
        box.to_edge(LEFT, buff=0.85).shift(DOWN * 0.25)
        lid = self._make_lid(box)
        question = self._he_text("כמה בקבוקים יש?", font_size=29, color=self.TEXT)
        question.next_to(box, DOWN, buff=0.35)
        cue = self._he_text(
            "אנחנו רוצים כלל אחד שסופר כל קופסה.",
            font_size=23,
            color=self.TEXT,
        ).to_edge(DOWN, buff=0.35)

        self.play(Write(title), FadeIn(VGroup(box[0], box[2]), shift=DOWN * 0.15), FadeIn(lid))
        self.play(
            lid.animate.shift(UP * 0.35 + RIGHT * 0.15).rotate(-14 * DEGREES),
            LaggedStartMap(FadeIn, bottles, shift=UP * 0.12, lag_ratio=0.12),
            run_time=1.4,
        )
        self.play(Write(question), FadeIn(cue, shift=UP * 0.12))
        self.wait(0.5)

        self.beat("base_case", label="קופסה ריקה מחזירה אפס")
        self._fade_out_all()
        title = self._scene_title("מקרה בסיס")
        empty_box, _ = self._make_box(0, "קופסה ריקה")
        empty_box.to_edge(LEFT, buff=0.95).shift(DOWN * 0.2)
        machine = self._make_machine("ספור(קופסה ריקה)")
        machine.move_to(RIGHT * 0.8 + DOWN * 0.1)
        output = self._result_token("0", self.BASE)
        output.next_to(machine, RIGHT, buff=0.75)
        base_label = self._tag("מקרה בסיס", self.BASE)
        base_label.next_to(empty_box, UP, buff=0.25)
        formula = self._he_text("ספור(קופסה ריקה) = 0", font_size=28, color=self.TEXT)
        formula.to_edge(DOWN, buff=0.42)
        input_arrow = Arrow(
            empty_box.get_right() + RIGHT * 0.1,
            machine.get_left() + LEFT * 0.1,
            buff=0.1,
            color=self.MUTED,
            stroke_width=3,
        )

        self.play(Write(title), FadeIn(empty_box), FadeIn(machine))
        self.play(Create(SurroundingRectangle(empty_box, color=self.BASE, buff=0.08)))
        self.play(FadeIn(base_label, shift=DOWN * 0.1), Create(input_arrow))
        box_copy = empty_box.copy()
        self.add(box_copy)
        self.play(box_copy.animate.scale(0.55).move_to(machine.get_center()), run_time=1.0)
        self.play(FadeOut(box_copy), machine.animate.set_fill(self.MACHINE, opacity=0.95))
        self.play(FadeIn(output, shift=RIGHT * 0.15), Write(formula))
        self.wait(0.5)

        self.beat("recursive_case_rule", label="מוציאים בקבוק אחד")
        self._fade_out_all()
        title = self._scene_title("מקרה רקורסיבי")
        box, bottles = self._make_box(self.BOTTLE_COUNT, "קופסה")
        box.to_edge(LEFT, buff=0.85).shift(DOWN * 0.25)
        selected = bottles[-1]
        rest_box, _ = self._make_box(self.BOTTLE_COUNT - 1, "שאר הקופסה")
        rest_box.move_to(box)
        one_label = self._tag("+ 1", self.RETURN)
        one_label.move_to(RIGHT * 1.1 + UP * 0.65)
        rule = self._he_text("ספור(קופסה) = 1 + ספור(השאר)", font_size=27, color=self.TEXT)
        rule.to_edge(DOWN, buff=0.42)
        recursive_tag = self._tag("מקרה רקורסיבי", self.RETURN)
        recursive_tag.next_to(box, UP, buff=0.25)

        self.play(Write(title), FadeIn(box))
        self.play(FadeIn(recursive_tag, shift=DOWN * 0.1), Indicate(selected, color=self.RETURN))
        bottle_copy = selected.copy()
        self.add(bottle_copy)
        self.play(
            bottle_copy.animate.move_to(one_label.get_center() + LEFT * 0.72).scale(1.08),
            selected.animate.set_opacity(0.16),
            run_time=1.0,
        )
        self.play(Transform(box, rest_box), FadeIn(one_label, shift=LEFT * 0.15))
        self.play(Write(rule))
        self.wait(0.5)

        self.beat("send_rest_back", label="אותה שאלה, קופסה קטנה יותר")
        machine = self._make_machine("ספור(קופסה)")
        machine.move_to(RIGHT * 1.0 + DOWN * 0.05)
        same_label = self._he_text("אותה שאלה, קופסה קטנה יותר", font_size=24, color=self.TEXT)
        same_label.next_to(machine, UP, buff=0.35)
        rest_arrow = Arrow(
            box.get_right() + RIGHT * 0.1,
            machine.get_left() + LEFT * 0.12,
            buff=0.1,
            color=self.MUTED,
            stroke_width=3,
        )
        rest_call = self._he_text("ספור(השאר)", font_size=26, color=self.MACHINE)
        rest_call.next_to(machine, DOWN, buff=0.22)

        self.play(FadeIn(machine, shift=LEFT * 0.15), FadeIn(same_label, shift=DOWN * 0.12))
        self.play(Create(rest_arrow), run_time=0.7)
        rest_copy = box.copy()
        self.add(rest_copy)
        self.play(rest_copy.animate.scale(0.52).move_to(machine.get_center()), run_time=1.1)
        self.play(
            FadeOut(rest_copy),
            Transform(machine[1], self._he_text("ספור(השאר)", font_size=25, color=WHITE).move_to(machine[1])),
            FadeIn(rest_call, shift=UP * 0.1),
        )
        self.wait(0.6)

        self.beat("unwind_answer", label="התשובות חוזרות למעלה")
        self._fade_out_all()
        title = self._scene_title("התשובות חוזרות")
        call_rows = self._make_call_rows(self.BOTTLE_COUNT)
        call_rows.to_edge(LEFT, buff=0.85).shift(DOWN * 0.15)
        base_highlight = SurroundingRectangle(call_rows[-1], color=self.BASE, buff=0.08)
        return_label = self._he_text(
            "כל בקבוק שחיכה מוסיף אחד.",
            font_size=25,
            color=self.TEXT,
        ).next_to(title, DOWN, buff=0.25)

        self.play(Write(title), FadeIn(call_rows, shift=DOWN * 0.12))
        self.play(FadeIn(return_label, shift=DOWN * 0.1), Create(base_highlight))
        previous_token = None
        for value in range(0, self.BOTTLE_COUNT + 1):
            row = call_rows[self.BOTTLE_COUNT - value]
            if value == 0:
                token = self._result_token("0", self.BASE)
            else:
                token = self._result_token(f"1 + {value - 1} = {value}", self.RETURN)
            token.next_to(row, RIGHT, buff=0.75)
            if previous_token is not None:
                arrow = Arrow(
                    previous_token.get_top() + UP * 0.04,
                    token.get_bottom() + DOWN * 0.04,
                    buff=0.08,
                    color=self.RETURN,
                    stroke_width=2.5,
                    max_tip_length_to_length_ratio=0.08,
                )
                self.play(Create(arrow), run_time=0.35)
            self.play(FadeIn(token, shift=RIGHT * 0.15), Indicate(row, color=self.RETURN), run_time=0.75)
            previous_token = token
        final = self._result_token(str(self.BOTTLE_COUNT), self.RETURN)
        final.scale(1.12)
        final.to_edge(RIGHT, buff=0.75).shift(UP * 0.4)
        final_label = self._he_text("הספירה הסופית", font_size=21, color=self.TEXT)
        final_label.next_to(final, UP, buff=0.18)
        self.play(FadeIn(final_label), TransformFromCopy(previous_token, final))
        self.wait(0.8)

        self.beat("final_recipe", label="שני כללים רקורסיביים")
        self._fade_out_all()
        title = self._scene_title("המתכון הרקורסיבי")
        summary_box, summary_bottles = self._make_box(2, "קופסה")
        summary_box.to_edge(LEFT, buff=0.9).shift(DOWN * 0.2)
        one = summary_bottles[-1].copy().set_color(self.RETURN)
        one.move_to(LEFT * 0.2 + UP * 0.65)
        rest, _ = self._make_box(1, "השאר")
        rest.scale(0.72).move_to(LEFT * 0.2 + DOWN * 0.55)
        split_arrow = Arrow(
            summary_box.get_right() + RIGHT * 0.05,
            rest.get_left() + LEFT * 0.05,
            buff=0.08,
            color=self.MUTED,
            stroke_width=2.5,
        )
        rules = VGroup(
            self._rule_line("קופסה ריקה", "0", self.BASE),
            self._rule_line("לא ריקה", "1 + ספור(השאר)", self.RETURN),
        ).arrange(DOWN, aligned_edge=RIGHT, buff=0.38)
        rules.to_edge(RIGHT, buff=0.75).shift(DOWN * 0.05)
        takeaway = self._he_text(
            "מקרה בסיס + אותה שאלה על קלט קטן יותר.",
            font_size=24,
            color=self.TEXT,
        ).to_edge(DOWN, buff=0.38)

        self.play(Write(title), FadeIn(summary_box))
        self.play(
            TransformFromCopy(summary_bottles[-1], one),
            Create(split_arrow),
            FadeIn(rest, shift=RIGHT * 0.12),
        )
        self.play(LaggedStartMap(FadeIn, rules, shift=LEFT * 0.12, lag_ratio=0.2))
        self.play(Write(takeaway))
        self.wait(1.2)

    def _he_text(self, text, **kwargs):
        return hebrew_text(text, **kwargs)

    def _scene_title(self, text):
        title = self._he_text(text, font_size=39, color=self.TEXT)
        title.to_edge(UP, buff=0.28)
        return title

    def _make_box(self, bottle_count, label):
        group, bottles = super()._make_box(bottle_count, "")
        group[2].become(self._he_text(label, font_size=22, color=self.TEXT).next_to(group[0], DOWN, buff=0.14))
        return group, bottles

    def _make_machine(self, label):
        body = RoundedRectangle(
            corner_radius=0.12,
            height=1.15,
            width=2.75,
            stroke_color=self.TEXT,
            stroke_width=2.5,
        )
        body.set_fill(self.MACHINE, opacity=0.88)
        text = self._he_text(label, font_size=23, color=WHITE)
        text.move_to(body)
        gear = Circle(radius=0.12, color=WHITE, stroke_width=2)
        gear.move_to(body.get_corner(UR) + LEFT * 0.27 + DOWN * 0.23)
        return VGroup(body, text, gear)

    def _make_call_rows(self, max_count):
        rows = VGroup()
        for count in range(max_count, -1, -1):
            if count == 0:
                label = "ספור(קופסה ריקה)"
            elif count == 1:
                label = "ספור(בקבוק אחד)"
            else:
                label = f"ספור({count} בקבוקים)"
            row = VGroup(
                RoundedRectangle(
                    corner_radius=0.08,
                    height=0.48,
                    width=3.0,
                    stroke_color=self.MUTED,
                    stroke_width=1.8,
                ),
                self._he_text(label, font_size=20, color=self.TEXT),
            )
            row[1].move_to(row[0])
            rows.add(row)
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.17)
        return rows

    def _result_token(self, label, color):
        token = super()._result_token(label, color)
        token[1].become(self._he_text(label, font_size=24, color=color).move_to(token[0]))
        return token

    def _tag(self, label, color):
        tag = RoundedRectangle(
            corner_radius=0.09,
            height=0.38,
            width=max(1.05, 0.18 * len(label) + 0.48),
            stroke_color=color,
            stroke_width=2,
        )
        tag.set_fill(self.BACKGROUND, opacity=1)
        text = self._he_text(label, font_size=18, color=color)
        text.move_to(tag)
        return VGroup(tag, text)

    def _rule_line(self, condition, result, color):
        line = self._he_text(f"{condition}  ->  {result}", font_size=25, color=color)
        return line
