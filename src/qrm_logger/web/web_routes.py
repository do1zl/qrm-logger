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
Web interface routes for QRM Logger spectrum analysis system.
Provides REST API endpoints for scheduler control, recording management, and file serving.
"""

import json
import logging
import threading
import time

from bottle import static_file, route, request, HTTPResponse, run

from qrm_logger.config.capture_definitions import capture_sets, get_capture_set_ids
from qrm_logger.core.config_manager import get_config_manager
from qrm_logger.utils.counter import get_counter
from qrm_logger.core.objects import CaptureParams
from qrm_logger.data.rms import get_rms_data_as_json
from qrm_logger.data.log import get_log_data_as_json
from qrm_logger.imaging.image_grid import get_grids
from qrm_logger.scheduling.scheduler import get_scheduler
from qrm_logger.sdr.sdr_factory import get_sdr_options
from qrm_logger.utils.util import free_disk_mb_for_path, VERSION
from qrm_logger.data.roi_store import load_roi_config, save_roi_config
from qrm_logger.recorder.recorder import get_recorder
from qrm_logger.execution import get_pipeline



@route('/system-info')
def system_info():
    """Return system information such as free disk space for the output directory."""
    try:
        from qrm_logger.config.output_directories import output_directory
        free_disk_mb = free_disk_mb_for_path(output_directory)
        return dict(data={
            'free_disk_mb': free_disk_mb
        })
    except Exception as e:
        logging.error(f"Error in system-info endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': str(e)}))

@route('/status')
def status():
    p = get_pipeline()
    is_recording = p.is_recording()

    record_time = ""
    if is_recording:
        sec = round(time.time() - p.get_record_start_time())
        minutes = sec // 60
        seconds = sec % 60
        record_time = f"{minutes:02d}:{seconds:02d}"

    record_progress = "SDR STARTUP"
    if is_recording:
        stat = p.get_recording_status()
        if stat and stat.operation:
            record_progress = str(stat.operation) + " [" + str(stat.current_job_number) + "/" + str(
                stat.jobs_total_number) + "]"

    # Pipeline errors first (most recent), SDR errors as fallback
    error_text = p.get_error_text() or get_recorder().get_error_text()

    sch = get_scheduler()
    next_scheduled = sch.get_next_scheduled_time()
    scheduler_status = sch.get_status()

    rv = {
        "recording": is_recording,
        "count": get_counter(),
        "record_time": record_time,
        "record_progress": record_progress,
        "next_scheduled": next_scheduled,
        "scheduler": scheduler_status,
        "error_text": error_text,
        "sdr_active": get_recorder().is_sdr_active(),
    }
    return dict(data=rv)


@route('/scheduler', method='POST')
def scheduler_control():
    """Control the scheduler: start, stop, or get status"""

    try:
        postdata = request.json
        action = postdata.get('action')

        if not action:
            return HTTPResponse(status=400, body=json.dumps({'error': 'Missing action parameter'}))

        if action == 'start':
            # Start the scheduler using configured mode and values (no request-provided interval)
            sch = get_scheduler()
            success = sch.start_scheduler()
            if success:
                return dict(data={'status': '', 'scheduler': sch.get_status()})
            else:
                return HTTPResponse(status=400, body=json.dumps({'error': 'Scheduler is already running'}))

        elif action == 'stop':
            sch = get_scheduler()
            success = sch.stop_scheduler()
            if success:
                return dict(data={'status': 'stopped', 'scheduler': sch.get_status()})
            else:
                return HTTPResponse(status=400, body=json.dumps({'error': 'Scheduler is not running'}))

        elif action == 'status':
            sch = get_scheduler()
            return dict(data={'scheduler': sch.get_status()})

        else:
            return HTTPResponse(status=400, body=json.dumps({'error': 'Invalid action. Use: start, stop, or status'}))

    except Exception as e:
        logging.error(f"Error in scheduler control: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': str(e)}))


@route('/config', method='GET')
def get_config():
    """Get all configuration values"""
    try:
        config_data = get_config_manager().get_all()
        config_data['version'] = VERSION
        return dict(data=config_data)
    except Exception as e:
        logging.error(f"Error getting configuration: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': str(e)}))



@route('/config', method='PUT')
def update_config():
    """Update configuration values"""
    try:
        postdata = request.json
        if not postdata:
            return HTTPResponse(status=400, body=json.dumps({'error': 'No configuration data provided'}))
        
        # Validate that all provided keys are valid configuration parameters
        valid_keys = {'rf_gain', 'if_gain', 'sdr_bandwidth', 'rec_time_default_sec',
                      'scheduler_cron', 'scheduler_autostart',
                      'fft_size', 'min_db', 'max_db',
                      'capture_sets_enabled', 'sdr_shutdown_after_recording',
                      'capture_set_configurations',
                      'timeslice_hours', 'timeslice_autogenerate'}
        provided_keys = set(postdata.keys())
        invalid_keys = provided_keys - valid_keys
        
        if invalid_keys:
            return HTTPResponse(status=400, body=json.dumps({
                'error': f'Invalid configuration keys: {list(invalid_keys)}. Valid keys are: {list(valid_keys)}'
            }))
        
        # Update configuration values
        updated_values = {}
        for key, value in postdata.items():
            get_config_manager().set(key, value)
            updated_values[key] = value
        get_config_manager().save_config()

        # Return the updated configuration
        current_config = get_config_manager().get_all()
        return dict(data={
            'message': 'Configuration updated successfully',
            'updated': updated_values,
            'current_config': current_config
        })
        
    except Exception as e:
        logging.error(f"Error updating configuration: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': str(e)}))


@route('/sdr-options', method='GET')
def get_sdr_options_endpoint():
    """Get all SDR options including bandwidth, RF gain, and IF gain ranges."""
    try:
        sdr_options = get_sdr_options()
        return dict(data=sdr_options)
    except Exception as e:
        logging.error(f"Error getting SDR options: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': str(e)}))



@route('/start', method='POST')
def start_record():
    postdata = request.json or {}
    sample_time = postdata.get("sample_time")
    note = postdata.get("note")
    calibration = postdata.get("calibration", False)  # Default to False if not provided

    p = get_pipeline()
    if p.is_recording():
        return HTTPResponse(status=500, body=json.dumps({'msg': 'running'}))

    params = CaptureParams(rec_time_sec=sample_time, note=note, is_calibration=calibration)
    thr = threading.Thread(target=p.execute_capture, args=(params,), daemon=True)
    thr.start()

    time.sleep(0.3)
    return status()

@route('/stop', method='POST')
def stop_record():
    """Request to stop the current recording (cooperative)."""
    try:
        p = get_pipeline()
        if not p.is_recording():
            return HTTPResponse(status=400, body=json.dumps({'error': 'not running'}))
        ok = p.request_stop_recording()
        time.sleep(0.2)
        if ok:
            return status()
        else:
            return HTTPResponse(status=500, body=json.dumps({'error': 'failed to request stop'}))
    except Exception as e:
        logging.error(f"Error in stop endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': str(e)}))


@route('/sdr-control', method='POST')
def sdr_control():
    """Start or stop SDR based on 'sdr-active' boolean in JSON body."""
    try:

        if get_recorder().is_recording():
            return HTTPResponse(status=400, body=json.dumps({'error': 'Recording in progress'}))

        postdata = request.json or {}
        desired = postdata.get('sdr-active')
        if not isinstance(desired, bool):
            return HTTPResponse(status=400, body=json.dumps({'error': 'Missing or invalid sdr-active (boolean)'}))

        rec = get_recorder()
        ok = True
        if desired:
            ok = rec.create_receiver()
        else:
            rec.disconnect_receiver()

        return dict(data={
            'sdr_active': rec.is_sdr_active(),
            'ok': bool(ok)
        })
    except Exception as e:
        logging.error(f"Error in sdr-control endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': str(e)}))



@route('/capture_sets')
def capture_sets_endpoint():
    """Get list of available capture set IDs (includes ROI sets with _ROI suffix when enabled)."""
    try:

        all_ids = get_all_valid_capture_ids()

        return dict(data=all_ids)
    except Exception as e:
        logging.error(f"Error in capture_sets endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))


@route('/capture_sets_with_specs')
def capture_sets_with_specs_endpoint():
    """Get all capture sets with their full spec details.
    Returns: { 
        "capture_set_id": {
            "description": "Set description" or null,
            "specs": [
                {
                    "spec_index": 0,
                    "id": "spec_id",
                    "freq": 7000.0,
                    "span": 1000.0 or null,
                    "freq_range": {"freq_start": 6500, "freq_end": 7500, "margin": 50} or null
                },
                ...
            ]
        },
        ...
    }
    """
    try:
        result = {}
        # Add base capture sets (import dynamically to get current state)
        from qrm_logger.config.capture_definitions import capture_sets as current_capture_sets
        for cs in current_capture_sets:
            specs_data = []
            for spec in cs.specs:
                spec_dict = {
                    'spec_index': spec.spec_index,
                    'id': spec.id,
                    'freq': spec.freq,
                    'span': spec.span
                }
                # Add freq_range if it exists
                if spec.freq_range:
                    spec_dict['freq_range'] = {
                        'freq_start': spec.freq_range.freq_start,
                        'freq_end': spec.freq_range.freq_end,
                        'margin': spec.freq_range.crop_margin_khz
                    }
                else:
                    spec_dict['freq_range'] = None
                specs_data.append(spec_dict)
            
            # Store as object with description and specs
            result[cs.id] = {
                'description': cs.description,
                'specs': specs_data
            }
        
        # Add ROI sets from roi_store
        from qrm_logger.data.roi_store import get_roi_specs
        roi_specs = get_roi_specs()
        result.update(roi_specs)
        
        return dict(data=result)
    except Exception as e:
        logging.error(f"Error in capture_sets_with_specs endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))


@route('/grids')
def grids():
    """Return grid entries for a specific capture set (required).

    Query parameters:
        capture_set_id: required capture set identifier (e.g., 'BANDS' or 'BANDS_ROI')
    """
    try:
        capture_set_id = request.query.get('capture_set_id')
        if not capture_set_id or not isinstance(capture_set_id, str):
            return HTTPResponse(status=400, body=json.dumps({'error': 'capture_set_id is required'}))

        all_ids = get_all_valid_capture_ids()
        if not capture_set_id in all_ids:
            return HTTPResponse(status=400, body=json.dumps({'error': 'invalid capture_set_id'}))

        plot_type = request.query.get('plot_type')
        if plot_type not in ['waterfall', 'average']:
            return HTTPResponse(
                status=400,
                body=json.dumps({'error': 'plot_type must be "waterfall" or "average"'})
            )

        grids_list = get_grids(capture_set_id, plot_type=plot_type)
        return dict(data=grids_list)
    except Exception as e:
        logging.error(f"Error in grids endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))



@route('/rms_data')
def rms_data():
    """Get RMS data from CSV file as JSON for a specific capture set.
    
    Query parameters:
        capture_set_id: required capture set identifier (e.g., 'BANDS' or 'BANDS_ROI')
        type: 'standard' (default) or 'truncated' - specifies which RMS dataset to return
    """
    try:
        # Get the 'type' query parameter, default to 'standard'
        rms_type = request.query.get('type', 'standard')
        
        # Validate the rms_type parameter
        if rms_type not in ['standard', 'truncated']:
            return HTTPResponse(
                status=400, 
                body=json.dumps({'error': f'Invalid type parameter. Must be "standard" or "truncated", got "{rms_type}"'})
            )

        # Get and validate capture_set_id
        capture_set_id = request.query.get('capture_set_id')
        if not capture_set_id or not isinstance(capture_set_id, str):
            return HTTPResponse(status=400, body=json.dumps({'error': 'capture_set_id is required'}))

        all_ids = get_all_valid_capture_ids()
        if not capture_set_id in all_ids:
            return HTTPResponse(status=400, body=json.dumps({'error': 'invalid capture_set_id'}))

        # Load data for the specific set
        try:
            data = get_rms_data_as_json(capture_set_id, rms_type)
        except Exception:
            data = []

        # Return successful response
        return dict(data=data)

    except Exception as e:
        logging.error(f"Error in rms_data endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))


@route('/log_data')
def log_data():
    """Get processing logs (log.csv) as JSON for a specific capture set.

    Query parameters:
        capture_set_id: required string identifying the capture set (e.g., 'BANDS' or 'BANDS_ROI')
    """
    try:
        capture_set_id = request.query.get('capture_set_id')
        if not capture_set_id or not isinstance(capture_set_id, str):
            return HTTPResponse(status=400, body=json.dumps({'error': 'capture_set_id is required'}))

        all_ids = get_all_valid_capture_ids()
        if not capture_set_id in all_ids:
            return HTTPResponse(status=400, body=json.dumps({'error': 'invalid capture_set_id'}))

        try:
            data = get_log_data_as_json(capture_set_id)
        except Exception:
            data = []

        return dict(data=data)
    except Exception as e:
        logging.error(f"Error in log_data endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))


@route('/rois', method='GET')
def get_rois():
    try:
        cfg = load_roi_config()
        return dict(data=cfg)
    except Exception as e:
        logging.error(f"Error loading ROIs: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))


@route('/rois', method='PUT')
def put_rois():
    try:
        postdata = request.json
        if not isinstance(postdata, dict):
            return HTTPResponse(status=400, body=json.dumps({'error': "Body must be an object with 'processing_enabled' and 'rois'"}))

        ok = save_roi_config(postdata)
        if not ok:
            return HTTPResponse(status=500, body=json.dumps({'error': 'Failed to save ROI configuration'}))
        return dict(data=postdata)
    except ValueError as ve:
        return HTTPResponse(status=400, body=json.dumps({'error': str(ve)}))
    except Exception as e:
        logging.error(f"Error saving ROI configuration: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))


@route('/images')
def images():
    """Return list of image file paths for a specific capture spec, day, and grid type.
    
    Query parameters:
        capture_set_id: required capture set identifier (e.g., 'BANDS')
        capture_spec_id: required capture spec identifier (e.g., '7M' or '14M')
        grid_type: required plot type ('waterfall' or 'average')
        day: required date in YYYY-MM-DD format
        image_size: optional 'resized' or 'full' (default: 'resized')
    
    Returns:
        List of relative paths starting from date directory: {day}/{filename}
        Images are always sorted by count descending (latest first).
        The UI constructs the full URL using capture_set_id and image_size.
    """
    try:
        # Get and validate query parameters
        capture_set_id = request.query.get('capture_set_id')
        capture_spec_id = request.query.get('capture_spec_id')
        grid_type = request.query.get('grid_type')
        day = request.query.get('day')
        image_size = request.query.get('image_size', 'resized')
        
        if not all([capture_set_id, capture_spec_id, grid_type, day]):
            return HTTPResponse(
                status=400, 
                body=json.dumps({'error': 'Missing required parameters: capture_set_id, capture_spec_id, grid_type, day'})
            )

        all_ids = get_all_valid_capture_ids()
        if not capture_set_id in all_ids:
            return HTTPResponse(status=400, body=json.dumps({'error': 'invalid capture_set_id'}))

        
        if grid_type not in ['waterfall', 'average']:
            return HTTPResponse(
                status=400,
                body=json.dumps({'error': 'grid_type must be "waterfall" or "average"'})
            )
        
        # Validate image_size parameter
        if image_size not in ['resized', 'full']:
            image_size = 'resized'  # Default to resized if invalid
        
        # Load metadata for the specified day and plot type
        from qrm_logger.data.metadata import load_plot_metadata
        from qrm_logger.config.output_directories import subdirectory_plots_resized, subdirectory_plots_full
        
        metadata = load_plot_metadata(capture_set_id, day, grid_type)
        
        if not metadata:
            return dict(data=[])
        
        # Filter images by capture_spec_id (matching the 'capture_id' field in metadata)
        # The capture_id in metadata should match the capture spec id
        matching_images = []
        for filename, meta in metadata.items():
            if meta.get('capture_id') == capture_spec_id:
                matching_images.append({
                    'filename': filename,
                    'time': meta.get('time_string', ''),
                    'count': meta.get('count', ''),
                    'note': meta.get('note', '')
                })
        
        # Sort by count descending (latest first)
        matching_images.sort(key=lambda x: x['count'], reverse=True)
        
        # Return paths starting from date directory: {day}/{filename}
        # The UI will construct the full URL using capture_set_id and image_size
        image_paths = [
            f"{day}/{img['filename']}"
            for img in matching_images
        ]
        
        return dict(data=image_paths)
        
    except Exception as e:
        logging.error(f"Error in images endpoint: {e}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))



@route('/')
def index():
    resp = static_file('index.html', root='./ui')
    return _apply_cache_headers(resp)

@route('/assets/<filepath:path>')
def assets(filepath):
    resp = static_file(filepath, root='./ui')
    return _apply_cache_headers(resp)

@route('/output/<filepath:path>')
def static2(filepath):
    from qrm_logger.config.output_directories import output_directory
    return static_file(filepath, root=output_directory)
    #return _apply_cache_headers(resp)



def _apply_cache_headers(resp):
    try:
        # Read from static web server settings (backend-only)
        from qrm_logger.config.web_server import static_cache_max_age_sec as _max
    except Exception:
        _max = 3600
    try:
        max_age = int(_max)
    except Exception:
        max_age = 3600
    if max_age and max_age > 0:
        resp.set_header('Cache-Control', f'public, max-age={max_age}')
    else:
        # Explicitly disable caching
        resp.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        resp.set_header('Pragma', 'no-cache')
        resp.set_header('Expires', '0')
    return resp



@route('/timeslice_grids')
def timeslice_grids():
    """List available time-slice grids (across days) by hour for a capture set and plot type.
    Returns entries of the form: { hour, full, resized, last_updated }
    """
    try:
        capture_set_id = request.query.get('capture_set_id')
        plot_type = request.query.get('plot_type')
        if not capture_set_id or not plot_type:
            return HTTPResponse(status=400, body=json.dumps({'error': 'capture_set_id and plot_type are required'}))

        if plot_type not in ['waterfall', 'average']:
            return HTTPResponse(
                status=400,
                body=json.dumps({'error': 'plot_type must be "waterfall" or "average"'})
            )

        all_ids = get_all_valid_capture_ids()
        if not capture_set_id in all_ids:
            return HTTPResponse(status=400, body=json.dumps({'error': 'invalid capture_set_id'}))

        from qrm_logger.imaging.imge_grid_timeslice import get_timeslice_grids
        elems = get_timeslice_grids(capture_set_id, plot_type)
        return dict(data=elems)
    except Exception as ex:
        logging.error(f"Error in timeslice_grids endpoint: {ex}")
        return HTTPResponse(status=500, body=json.dumps({'error': 'Internal server error'}))



def get_all_valid_capture_ids():
    # Base sets from configuration (dynamically loaded)

    base_ids = get_capture_set_ids()

    # Dynamic ROI sets only when processing is enabled
    try:
        from src.qrm_logger.data.roi_store import load_roi_config
        cfg = load_roi_config()
        rois = cfg.get('rois', []) if cfg.get('processing_enabled', False) else []
    except Exception:
        rois = []
    roi_base_ids = sorted(list({r.get('base_capture_set_id') for r in rois if r.get('base_capture_set_id')}))
    roi_ids = [f"{sid}_ROI" for sid in roi_base_ids if isinstance(sid, str) and sid]

    # Merge while preserving base order, then ROI
    all_ids = base_ids + [rid for rid in roi_ids if rid not in base_ids]
    return all_ids


def thread_function_server():
    from qrm_logger.config.web_server import web_server_host, web_server_port
    logging.info("starting webserver "+web_server_host+":"+str(web_server_port))

    run(server='waitress', host=web_server_host, port=web_server_port, threads=10, quiet=True)


def run_bottle(config_mgr=None):
    thr = threading.Thread(target=thread_function_server, args=(), daemon=True)
    thr.start()
