# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 DO1ZL
# This file is part of qrm-logger.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import logging
import threading
import time

from gnuradio import gr

from qrm_logger.core.config_manager import get_config_manager
from qrm_logger.config.recording_params import (
    frequency_change_delay_sec,
    frame_rate_default,
    capture_timeout_margin_sec,
)
from qrm_logger.config.sdr_hardware import device_name
from qrm_logger.core.objects import RecordingStatus, CaptureRun
from qrm_logger.recorder.fft_receiver import fft_receiver


# Safety limit for the GNU Radio flowgraph shutdown. Stopping a device that is
# already gone can block in wait(), which would hang the recording thread in the
# very situation the teardown is meant to recover from.
sdr_stop_timeout_sec = 15


class Recorder:
    _instance = None
    _initialized = False

    receiver = None
    recording = False
    error_text = None

    stop_requested = False

    def __new__(cls, config_file_path: str = None):
        if cls._instance is None:
            cls._instance = super(Recorder, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_file_path: str = None):
        if Recorder._initialized:
            return

    def is_sdr_active(self):
        return self.receiver is not None


    def is_recording(self):
        return self.recording

    def get_error_text(self):
        return self.error_text

    def clear_error(self):
        self.error_text = None

    def on_record_start(self):
        # Flagged as busy right away, so that the SDR cannot be shut down while starting up
        self.recording = True
        started = False
        try:
            if not self.receiver:
                if not self.create_receiver():
                    return False
            started = self.start_receiver()
            return started
        finally:
            if not started:
                # Startup failed: do not leave the recorder flagged as busy
                self.recording = False

    def on_record_end(self):
        logging.info("Recording session complete")
        try:
            self.stop_receiver()
            if get_config_manager().get("sdr_shutdown_after_recording", True):
                self.disconnect_receiver()
        except Exception as e:
            # Do not mask the error that ended the recording; drop the receiver
            # so the next run creates a fresh one instead of reusing a broken flowgraph
            logging.error(f"Failed to shut down SDR cleanly: {e}")
            self.receiver = None
        finally:
            self.recording = False


    def create_receiver(self):
        logging.info("create_receiver")
        success = False
        self.error_text = None
        try:
            logging.info("Init Receiver. Using GNU Radio " + gr.version())
            self.stop_requested = False

            sample_rate = get_config_manager().get("sdr_bandwidth") * 1000
            frequency = 3300000

            self.receiver = fft_receiver(
                samp_rate=sample_rate,
                freq=frequency,
                fft_size=get_config_manager().get("fft_size"),
                framerate=frame_rate_default,
            )

            success = True
        except Exception as ex:
            logging.error("could not start SDR: "+str(ex))
            self.error_text = str(ex)
            self.receiver = None
            raise
        return success


    def start_receiver(self):
        if self.receiver:
            return self._start_receiver_internal()
        return False

    def stop_receiver(self):
        if self.receiver:
            self._stop_receiver_internal()

    def disconnect_receiver(self):
        if self.receiver:
            self.receiver.stop()
            self._disconnect_internal()
            self.receiver = None


    def request_stop(self):
        """Request cooperative stop of the current/next capture run."""
        logging.info("stop requested")
        self.stop_requested = True
        try:
            self.receiver.fft_record_sink.stop_now()
        except Exception as e:
            logging.error(f"failed to stop sink: {e}")




    def _start_receiver_internal(self):
        logging.info("starting SDR")

        self.receiver.set_gain()
        # Mark start for time-to-first-FFT-frame measurement
        self.receiver.fft_record_sink.mark_receiver_start()
        try:
            self.receiver.start()
        except Exception as e:
            logging.error(f"Failed to start SDR: {e}")
            self.error_text = "Failed to start SDR: " + (str(e) or type(e).__name__)
            return False
        return True



    def _stop_receiver_internal(self):
        logging.info(f"Stopping SDR ({device_name})...")
        receiver = self.receiver

        def _stop_and_wait():
            receiver.stop()
            receiver.wait()

        stopper = threading.Thread(target=_stop_and_wait, name="sdr-stop", daemon=True)
        stopper.start()
        stopper.join(sdr_stop_timeout_sec)
        if stopper.is_alive():
            # Let on_record_end() drop the receiver, so the next run builds a fresh one
            raise RuntimeError(f"SDR did not stop within {sdr_stop_timeout_sec} s")

    def _disconnect_internal(self):
        logging.info(f"Shutting down SDR ({device_name})...")
        self.receiver.disconnect_all()


    def execute_recordings(self, status: RecordingStatus,  sets_to_record, capture_params):
        if self.receiver:
            sets_recorded = []
            cancelled = False
            for s in sets_to_record:
                logging.info("record capture set: " + str(s.id))
                runs = self._create_capture_runs(s, capture_params)

                status.operation = "RECORDING " + s.id
                completed = self.start_capture_runs(status, runs)

                logging.info("recording completed" if completed else "recording cancelled")
                sets_recorded.append((s, runs))
                if not completed:
                    cancelled = True
                    break
            return sets_recorded, cancelled
        else:
            logging.error("Recording error: No Receiver")
            return  [], True



    def _create_capture_runs(self, capture_set,  capture_params):
        """Create CaptureRun objects from capture set specs."""

        date_string = capture_params.recording_start_datetime.strftime('%Y-%m-%d')

        # Load per-capture-set configurations (kHz bandwidth), if any
        cfgs = get_config_manager().get("capture_set_configurations") or {}
        if not isinstance(cfgs, dict):
            cfgs = {}

        runs = []
        for spec in capture_set.specs:
            if spec.span is None:
                # Use per-set bandwidth override if provided; else fall back to global SDR bandwidth
                bw_khz = None
                try:
                    entry = cfgs.get(capture_set.id)
                    if isinstance(entry, dict):
                        bw_khz = entry.get('bandwidth')
                except Exception:
                    bw_khz = None
                span = None
                if bw_khz is not None:
                    try:
                        span = int(bw_khz) * 1000
                    except (TypeError, ValueError):
                        span = None
                if span is None:
                    span = get_config_manager().get("sdr_bandwidth") * 1000
            else:
                span = spec.span * 1000
            freq = spec.freq * 1000
            cj = CaptureRun(
                id=spec.id,
                freq=freq,
                span=span,
                position=spec.spec_index,
                counter=capture_params.counter,
                capture_set_id=capture_set.id,
                date_string=date_string,
                fft_size=get_config_manager().get("fft_size"),
                rec_time_ms=capture_params.rec_time_sec * 1000,
                time=capture_params.recording_start_datetime,
                spec=spec,
            )
            runs.append(cj)
        return runs


    def start_capture_runs(self, status: RecordingStatus, runs):
        """Start a batch of capture runs.
        Returns True if all runs completed, or False if a stop was requested.
        """
        status.jobs_total_number = len(runs)
        number = 0
        try:
            for run in runs:
                if self._check_if_stopped():
                    break

                self.receiver.set_frequency(run.freq)
                self.receiver.set_sample_rate(run.span)

                time.sleep(frequency_change_delay_sec)

                self.receiver.fft_record_sink.start_record(run)
                self._wait_for_run(run)

                number = number + 1
                status.current_job_number = number

            cancelled = self.stop_requested
            return not cancelled
        finally:
            # Reset the flag for future batches, also when a run raised
            self.stop_requested = False

    def _wait_for_run(self, run):
        """Wait for a capture run to finish, or raise if the SDR goes silent.

        The sink only leaves the recording state while it receives samples, so a
        device that disappears mid-run (USB unplug, driver error) never ends the
        run and never raises: librtlsdr reports the failure on its own thread and
        the source block simply stops producing. The deadline is what turns that
        silence into an error.
        """
        deadline = time.monotonic() + run.rec_time_ms / 1000.0 + capture_timeout_margin_sec

        while self.receiver.fft_record_sink.is_recording:
            if self._check_if_stopped():
                return
            if time.monotonic() > deadline:
                self._abort_stalled_run(run)
            time.sleep(0.1)

    def _abort_stalled_run(self, run):
        message = (
            f"SDR delivered no data for {run.id} within "
            f"{round(run.rec_time_ms / 1000.0 + capture_timeout_margin_sec, 1)} s "
            f"- device stalled or disconnected"
        )
        logging.error(message)
        self.error_text = message
        try:
            # Release the sink, so it does not stay armed for the next run
            self.receiver.fft_record_sink.stop_now()
        except Exception as e:
            logging.error(f"failed to stop sink after stall: {e}")
        # Abort the batch: the remaining runs would hit the same dead device
        raise RuntimeError(message)


    def _check_if_stopped(self):
        if self.stop_requested:
            # Cooperatively stop current recording
            try:
                self.receiver.fft_record_sink.stop_now()
            except Exception:
                pass
            return True


# Singleton instance function
def get_recorder() -> Recorder:
    """Get the singleton Recorder instance"""
    return Recorder()
