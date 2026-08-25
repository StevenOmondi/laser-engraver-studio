import unittest

from laserengraver.core.gcode import frame_gcode, gcode_segments, gcode_stats, gcode_to_svg, line_may_fire_laser


class GCodeTests(unittest.TestCase):
    def test_stats_ignore_mode_commands_as_motion(self):
        gcode = "G21\nG90\nG0 X5 Y5\nM4 S100\nG1 X10 Y15 F1200\nM5\n"

        stats = gcode_stats(gcode)

        self.assertEqual(stats.motion_lines, 2)
        self.assertEqual(stats.max_power, 100)
        self.assertEqual(stats.min_x, 5)
        self.assertEqual(stats.max_y, 15)

    def test_segments_track_laser_and_rapid_moves(self):
        gcode = "G90\nG0 X1 Y1\nM4 S200\nG1 X2 Y1 F1000\nM5\nG0 X0 Y0\n"

        segments = gcode_segments(gcode)

        self.assertEqual(len(segments), 3)
        self.assertTrue(segments[0]["rapid"])
        self.assertTrue(segments[1]["laser"])
        self.assertFalse(segments[2]["laser"])

    def test_laser_guard_is_conservative(self):
        self.assertTrue(line_may_fire_laser("M4 S10"))
        self.assertTrue(line_may_fire_laser("G1 X1 S10"))
        self.assertFalse(line_may_fire_laser("M5"))
        self.assertFalse(line_may_fire_laser("G0 X1 Y1"))

    def test_frame_gcode_is_laser_off(self):
        frame = frame_gcode("G90\nG0 X10 Y10\nG1 X20 Y20\n")

        self.assertIn("Dry frame preview", frame)
        self.assertNotIn("M3", frame)
        self.assertNotIn("M4", frame)

    def test_svg_preview_renders_toolpath(self):
        svg = gcode_to_svg("G90\nG0 X0 Y0\nM4 S100\nG1 X20 Y10\n", "Preview")

        self.assertIn("<svg", svg)
        self.assertIn("<line", svg)
        self.assertIn("Preview", svg)


if __name__ == "__main__":
    unittest.main()
