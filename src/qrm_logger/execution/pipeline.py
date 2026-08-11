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

"""
Execution pipeline for spectrum recording sessions.
Coordinates recording workflow, plot generation, and grid creation for CaptureSets.
Also serves as the singleton source of truth for current recording state.
"""

import logging
import os
import time
import traceback
from datetime import datetime

from qrm_logger.config.output_directories import keep_raw_files
from qrm_logger.core.config_manager import get_config_manager
from qrm_logger.execution.data_exporter import process_grids, process_spectrum_data, _get_db_configurations
from qrm_logger.core.objects import RecordingStatus, CaptureParams
from qrm_logger.data.log import clear_all_collected_log_texts
from qrm_logger.data.rms import write_rms
from qrm_logger.data.roi_store import  process_rois
from qrm_logger.recorder.recorder import get_recorder
import copy as _copy

from qrm_logger.utils.counter import get_counter
from qrm_logger.utils.counter import inc_counter

from src.qrm_logger.execution.data_exporter import process_timeslice_grids

class Pipeline:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Pipeline, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if Pipeline._initialized:
            return
        # Execution state
        self.running = False
        self.recording = False
        self.record_start_time = 0
        self.recording_status: RecordingStatus | None = None
        self.error_text: str | None = None
        Pipeline._initialized = True

    # ------ Recording state accessors ------
    def is_running(self):
        return self.running

    def is_recording(self):
        return self.recording

    def get_record_start_time(self):
        return self.record_start_time

    def get_recording_status(self):
        return self.recording_status

    def get_error_text(self):
        return self.error_text

    def execute_capture_default(self):
        capture_params = CaptureParams(rec_time_sec=None, note=None, is_calibration=False)
        self.execute_capture(capture_params)

    def execute_capture(self, capture_params: CaptureParams):
        if self.recording:
            logging.warn("recording in progress, skip execution")
            return

        self.recording = True
        self.record_start_time = time.time()
        self.recording_status = RecordingStatus()
        # Drop the error of the previous run, so the UI only shows current ones
        self.error_text = None
        get_recorder().clear_error()

        # Populate capture params
        counter = inc_counter()
        capture_params.counter = counter
        capture_params.recording_start_datetime = datetime.now()
        if not capture_params.rec_time_sec:
            capture_params.rec_time_sec = get_config_manager().get("rec_time_default_sec")  # seconds

        try:
            self.execute(self.recording_status, capture_params)
        finally:
            # Clear state regardless of success/failure
            self.recording_status = None
            self.recording = False
            self.record_start_time = 0

    def request_stop_recording(self) -> bool:
        """Request stopping the current recording cooperatively."""
        if not self.recording:
            logging.info("stop_recording: not recording")
            return False
        try:
            if self.recording_status:
                self.recording_status.operation = "CANCEL"
                self.recording_status.cancel_requested = True
            get_recorder().request_stop()
            return True
        except Exception as e:
            logging.error(f"Error stopping recording: {e}")
            return False

    # ------ Core execution implementation ------
    def execute(self, status: RecordingStatus,  capture_params: CaptureParams):
        """Entry-point used by the scheduler to execute a full batch."""
        self.running = True
        cancelled = False

        try:
            logging.info("#" * 100)
            logging.info("#" * 100)
            logging.info("run # " + str(capture_params.counter))

            enabled_sets = set(get_config_manager().get("capture_sets_enabled"))
            # Import capture_sets dynamically to get current state
            from qrm_logger.config.capture_definitions import capture_sets
            sets_to_record = [cs for cs in capture_sets if cs.id in enabled_sets]
            logging.info("recording sets: " + str(len(sets_to_record)) + "/" + str(len(capture_sets)))

            #######################################################
            success = get_recorder().on_record_start()
            if not success:
                return

            sets_recorded = []
            try:
                if status.cancel_requested:
                    logging.info("Recording cancelled")
                    return

                sets_recorded, cancelled = get_recorder().execute_recordings(status, sets_to_record, capture_params)
            finally:
                # Always release the SDR, also when recording raised
                get_recorder().on_record_end()

            if cancelled or status.cancel_requested:
                logging.info("Processing cancelled")
                return

            #######################################################

            self.process_sets(status, sets_recorded, capture_params)

            logging.info("#" * 100)
            logging.info("Processing completed")


        except Exception as e:
            logging.error(f"Pipeline failed during execution: {str(e)}")
            logging.error(traceback.format_exc())
            status.operation = "ERROR"
            self.error_text = str(e) or type(e).__name__
            raise
        finally:
            clear_all_collected_log_texts()
            self.running = False

    def process_sets(self, status, sets_recorded, capture_params):

        for capture_set, runs in sets_recorded:
            capture_params1 = _copy.deepcopy(capture_params)

            # Process spectrum data
            results = process_spectrum_data(runs, status, capture_params1)

            if getattr(status, "cancel_requested", False):
                logging.info("Processing cancelled; skipping finalize and remaining sets.")
                t_processing_end = time.perf_counter()
                break

            # Finalize processing (generate grids and write RMS data)
            self._finalize_processing(status, results, capture_params)

            # ROI post-processing (plots + grid only, skip RMS)
            try:
                process_rois(capture_set, runs, status, capture_params)
            except Exception as e:
                logging.error(f"ROI processing failed for set {capture_set.id}: {e}")

            if not keep_raw_files:
                self._cleanup_raw_files(runs)
            t_processing_end = time.perf_counter()

        # adjust counter after calibration
        if capture_params.is_calibration:
            db_configs = _get_db_configurations(capture_params.is_calibration)
            for c in range(1, len(db_configs)):
                inc_counter()
            logging.info("calibration: adjusted counter to " + str(get_counter()))

    def _finalize_processing(self, status: RecordingStatus, results, capture_params):
        status.operation = "GRID"
        if results:
            first_run = results[0].run
            capture_set_id = first_run.capture_set_id
            process_grids(capture_set_id, first_run.date_string)
            write_rms(capture_set_id, results,  capture_params)
            process_timeslice_grids(capture_set_id, capture_params)

    def _cleanup_raw_files(self, runs):
        for run in runs:
            raw_filename = run.raw_filename
            try:
                if os.path.exists(raw_filename):
                    os.remove(raw_filename)
                    logging.debug(f"Deleted raw file: {raw_filename}")
            except Exception as delete_error:
                logging.error(f"Failed to delete raw file {raw_filename}: {delete_error}")
        logging.info("Raw file cleanup completed")


# Singleton accessor

def get_pipeline() -> Pipeline:
    return Pipeline()
