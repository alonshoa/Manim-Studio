from manim import *
import numpy as np


class ParametricCurve3D(ThreeDScene):
    RADIUS = 3.0
    Z_SCALE = 0.45
    START_U = -3 * TAU
    INITIAL_END_U = START_U + 0.01
    END_U = 1.25 * TAU
    CAMERA_PHI = 70 * DEGREES
    CAMERA_THETA = -30 * DEGREES

    def construct(self):
        axes = ThreeDAxes().add_coordinates()
        end_tracker = ValueTracker(self.INITIAL_END_U)

        curve = always_redraw(
            lambda: ParametricFunction(
                self._helix,
                color=BLUE,
                t_range=[self.START_U, end_tracker.get_value()],
            )
        )
        radius_line = always_redraw(
            lambda: Line(
                start=ORIGIN,
                end=curve.get_end(),
                color=BLUE,
            ).add_tip()
        )
        title = Text("Parametric 3D Curve", font_size=34)
        title.to_edge(UP)

        self.set_camera_orientation(phi=self.CAMERA_PHI, theta=self.CAMERA_THETA)
        self.add_fixed_in_frame_mobjects(title)
        self.play(FadeIn(title), Create(axes))
        self.add(curve, radius_line)
        self.play(end_tracker.animate.set_value(self.END_U), run_time=4, rate_func=linear)
        self.wait()

    def _helix(self, u):
        return np.array(
            [
                self.RADIUS * np.cos(u),
                self.RADIUS * np.sin(u),
                self.Z_SCALE * u,
            ]
        )
