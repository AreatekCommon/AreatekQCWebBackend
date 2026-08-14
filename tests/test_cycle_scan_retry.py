from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from app.eki.constants import PATH_STATUS_IDLE
from app.eki.messages import TrajectoryPoint
from app.pipeline.cycle import CycleRunResult, _run_scan_until_aligned, run_cycle
from q12_client import SdkCommandError, SNSDK_ERR_MARKER_TRACK_FAILED


def make_point(
    index: int,
    point_type: str,
    *,
    a7: float = 0.0,
    axes: list[float] | None = None,
) -> TrajectoryPoint:
    return TrajectoryPoint(
        index=index,
        guid=str(index),
        point_type=point_type,
        comment=point_type,
        speed=50.0,
        acceleration=50.0,
        a7=a7,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=axes if axes is not None else [float(index)] * 6,
    )


def make_single_scan_trajectory() -> list[TrajectoryPoint]:
    return [
        make_point(0, "home"),
        make_point(1, "scan", a7=0.0),
        TrajectoryPoint(
            index=2,
            guid="2",
            point_type="end",
            comment="end",
            speed=50.0,
            acceleration=50.0,
            a7=0.0,
            a7_speed=50.0,
            a7_acceleration=50.0,
            axes=[0.0] * 6,
        ),
    ]


class RunScanUntilAlignedTests(unittest.TestCase):
    def test_succeeds_after_retryable_failures(self) -> None:
        point = make_point(1, "scan")
        scanner = MagicMock()
        scanner.run_scan.side_effect = [
            SdkCommandError(
                "startScan",
                SNSDK_ERR_MARKER_TRACK_FAILED,
                "result=failed",
                finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
                result="failed",
            ),
            SdkCommandError(
                "startScan",
                SNSDK_ERR_MARKER_TRACK_FAILED,
                "result=failed",
                finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
                result="failed",
            ),
            None,
        ]

        with patch("app.pipeline.cycle._sleep_interruptible"):
            _run_scan_until_aligned(scanner, 1, point, retry_delay_sec=0.0)

        self.assertEqual(scanner.run_scan.call_count, 3)

    def test_raises_non_retryable_error_immediately(self) -> None:
        point = make_point(1, "scan")
        scanner = MagicMock()
        scanner.run_scan.side_effect = SdkCommandError("setScanParas", 40, "invalid params")

        with self.assertRaises(SdkCommandError):
            _run_scan_until_aligned(scanner, 1, point, retry_delay_sec=0.0)

        scanner.run_scan.assert_called_once()

    def test_abort_during_retry_sleep(self) -> None:
        point = make_point(1, "scan")
        scanner = MagicMock()
        scanner.run_scan.side_effect = SdkCommandError(
            "startScan",
            SNSDK_ERR_MARKER_TRACK_FAILED,
            "result=failed",
            finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
            result="failed",
        )
        abort_event = threading.Event()

        with patch("app.pipeline.cycle._sleep_interruptible") as sleep_mock:
            sleep_mock.side_effect = RuntimeError("Cycle aborted")
            with self.assertRaises(RuntimeError) as ctx:
                _run_scan_until_aligned(
                    scanner,
                    1,
                    point,
                    abort_event=abort_event,
                    retry_delay_sec=0.0,
                )

        self.assertEqual(str(ctx.exception), "Cycle aborted")
        scanner.run_scan.assert_called_once()


class CycleScanRetryIntegrationTests(unittest.TestCase):
    def test_run_cycle_completes_after_alignment_retries(self) -> None:
        points = make_single_scan_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()
        scanner.run_scan.side_effect = [
            SdkCommandError(
                "startScan",
                SNSDK_ERR_MARKER_TRACK_FAILED,
                "result=failed",
                finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
                result="failed",
            ),
            SdkCommandError(
                "startScan",
                SNSDK_ERR_MARKER_TRACK_FAILED,
                "result=failed",
                finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
                result="failed",
            ),
            None,
        ]
        scanner.generate_mesh_and_save.return_value = None

        with patch("app.pipeline.cycle._sleep_interruptible"), patch(
            "app.pipeline.cycle._finalize_mesh_worker",
            return_value=None,
        ):
            result = run_cycle(robot, scanner, "scan_test")

        self.assertEqual(result.project_name, "scan_test")
        self.assertEqual(scanner.run_scan.call_count, 3)

    def test_run_cycle_propagates_fatal_scan_error(self) -> None:
        points = make_single_scan_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)

        scanner = MagicMock()
        scanner.run_scan.side_effect = SdkCommandError(
            "startScan",
            29,
            "result=NO_GLOBAL_MARKERS",
            result="NO_GLOBAL_MARKERS",
        )

        with patch("app.pipeline.cycle._sleep_interruptible"):
            with self.assertRaises(SdkCommandError):
                run_cycle(robot, scanner, "scan_test")

        scanner.run_scan.assert_called_once()


class SkipFailedScansTests(unittest.TestCase):
    def test_skips_alignment_failure_when_enabled(self) -> None:
        point = make_point(1, "scan")
        scanner = MagicMock()
        scanner.run_scan.side_effect = SdkCommandError(
            "startScan",
            SNSDK_ERR_MARKER_TRACK_FAILED,
            "result=failed",
            finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
            result="failed",
        )

        with patch("app.pipeline.cycle._sleep_interruptible") as sleep_mock:
            _run_scan_until_aligned(
                scanner,
                1,
                point,
                retry_delay_sec=0.0,
                skip_failed_scans=True,
            )

        scanner.run_scan.assert_called_once()
        sleep_mock.assert_not_called()

    def test_fatal_error_still_aborts_when_skip_enabled(self) -> None:
        point = make_point(1, "scan")
        scanner = MagicMock()
        scanner.run_scan.side_effect = SdkCommandError(
            "startScan",
            29,
            "result=NO_GLOBAL_MARKERS",
            result="NO_GLOBAL_MARKERS",
        )

        with self.assertRaises(SdkCommandError):
            _run_scan_until_aligned(
                scanner,
                1,
                point,
                retry_delay_sec=0.0,
                skip_failed_scans=True,
            )

        scanner.run_scan.assert_called_once()

    def test_run_cycle_continues_after_skipped_alignment_scan(self) -> None:
        points = make_single_scan_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()
        scanner.run_scan.side_effect = SdkCommandError(
            "startScan",
            SNSDK_ERR_MARKER_TRACK_FAILED,
            "result=failed",
            finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
            result="failed",
        )
        scanner.generate_mesh_and_save.return_value = None

        settings = MagicMock()
        settings.pipeline.skip_failed_scans = True

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=settings,
        ), patch("app.pipeline.cycle._sleep_interruptible"), patch(
            "app.pipeline.cycle._finalize_mesh_worker",
            return_value=None,
        ):
            result = run_cycle(robot, scanner, "scan_test")

        self.assertEqual(result.project_name, "scan_test")
        scanner.run_scan.assert_called_once()
        scanner.generate_mesh_and_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
