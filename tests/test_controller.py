import unittest

from laserengraver.core.controller import GrblSerialController


class FailingSerial:
    def write(self, payload):
        raise PermissionError(13, "Access is denied")

    def flush(self):
        pass

    def close(self):
        pass


class ControllerStatusTests(unittest.TestCase):
    def test_status_parser_tracks_active_limit_pins(self):
        controller = GrblSerialController()

        controller._parse_status_line("<Idle|MPos:1.000,2.000,0.000|FS:0,0|Pn:XY>")

        status = controller.status().to_dict()
        self.assertEqual(status["active_pins"], ["X", "Y"])
        self.assertTrue(status["limit_switches"]["x"])
        self.assertTrue(status["limit_switches"]["y"])
        self.assertFalse(status["limit_switches"]["z"])

    def test_status_parser_clears_inactive_pins(self):
        controller = GrblSerialController()

        controller._parse_status_line("<Idle|MPos:0.000,0.000,0.000|FS:0,0|Pn:X>")
        controller._parse_status_line("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")

        self.assertEqual(controller.status().to_dict()["active_pins"], [])

    def test_serial_write_failure_marks_controller_disconnected(self):
        controller = GrblSerialController()
        controller.connected = True
        controller.state = "Idle"
        controller.port = "COM_TEST"
        controller._serial = FailingSerial()

        with self.assertRaises(PermissionError):
            controller.send_line("?")

        status = controller.status().to_dict()
        self.assertFalse(status["connected"])
        self.assertEqual(status["state"], "Disconnected")
        self.assertEqual(status["active_pins"], [])


if __name__ == "__main__":
    unittest.main()
