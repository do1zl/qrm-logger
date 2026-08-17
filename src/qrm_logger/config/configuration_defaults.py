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
Default TOML configuration template for QRM Logger.
This template is used to generate config-static.toml on first start.
"""

DEFAULT_CONFIG_TOML = """# QRM Logger Configuration
# Auto-generated on first start - edit freely
# Changes take effect after application restart

# =============================================================================
# ANALYSIS CONFIGURATION
# =============================================================================

[analysis]
# Frequencies to exclude from RMS analysis (kHz)
#  - 0 kHz targets baseband/DC artifacts
#  - 28800 kHz is the RTL-SDR Blog V4 upconverter LO frequency
exclude_freqs_khz = [0.0, 28800.0]

# =============================================================================
# OUTPUT PATH CONFIGURATION
# =============================================================================

[paths]
# Base output directory for all generated files
output_directory = "./_recordings"

# Keep raw files after plot generation
# If false: raw files are deleted after plots are created (saves disk space)
# If true: raw files are preserved for later analysis or debugging
keep_raw_files = false

# =============================================================================
# RECORDING PARAMETERS
# =============================================================================

[recording]
# Recording time in seconds (default value for config-dynamic.json)
rec_time_default_sec = 2

# Frame rate for GNU Radio processing
frame_rate_default = 25

# Wait time after changing the frequency (seconds)
# Recommended values: RTLSDR 0.5, SDRplay 2
frequency_change_delay_sec = 0.5

# Extra time granted to a capture run before the SDR is considered stalled (seconds)
# Catches a device that stops delivering samples, e.g. after being unplugged
capture_timeout_margin_sec = 10

[recording.fft]
# FFT size for spectrum analysis (must be power of 2)
# Higher values = better frequency resolution but slower processing
# Common values: 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072
fft_size_default = 65536

# FFT Smoothing/Averaging Configuration
# avg_alpha controls exponential averaging of FFT data (0.0 to 1.0)
# 1.0 = no averaging (raw FFT data)
# 0.1 = heavy smoothing, 0.5 = moderate smoothing, 0.9 = light smoothing
fft_avg_alpha = 0.7

# Spectrum range configuration for plot generation (dB scale limits)
min_db = -85
max_db = -60

# =============================================================================
# SCHEDULER CONFIGURATION
# =============================================================================

[scheduler]
# Automatically start the scheduler when the application starts from command line
# If true: scheduler starts immediately when main.py runs
# If false: scheduler must be started manually via web interface
autostart = false

# Cron expression in standard crontab format
# Tip: Prefer day-of-week names (mon-sun) instead of numbers to avoid ambiguity
# Examples:
#   "*/15 * * * *"              -> every 15 minutes
#   "0 * * * *"                 -> at minute 0 of every hour
#   "*/5 18-21 * * *"           -> every 5 minutes from 18:00 to 21:59
#   "*/10 6-8,17-20 * * mon-fri" -> every 10 minutes during commute hours on weekdays
cron = "*/15 * * * *"

# =============================================================================
# SDR HARDWARE CONFIGURATION
# =============================================================================

[sdr]
# SDR device type to use: "rtlsdr" or "sdrplay"
device_name = "rtlsdr"

# RF gain setting for the SDR device
# for RTLSDR: 0 to 50 dB (discrete steps, typical 0-40 dB). Default: 0 dB
# for SDRPlay RF: 0 to -24 dB (frequency dependent). Recommended value: -18
rf_gain = 0

# IF gain setting for the SDR device (SDRPlay only)
# for SDRPlay IF: -20 to -59 dB. Recommended value: -35
if_gain = -35

# Bias-T power supply setting
# Enables DC voltage on antenna port to power LNAs or other active antennas
# WARNING: Only enable if your antenna/LNA requires bias-T power
# Applies to both RTLSDR (if supported by hardware) and SDRPlay devices
# NOTE: Bias-T will remain active after recording ends. To disable it, set this to false and run another recording.
bias_t_enabled = false

# Shutdown SDR device after recording to save energy and reduce idle temperature
# If true: SDR is stopped and fully disconnected between recordings (default)
#   Benefits: Lower idle power, reduced device temperature
#   Tradeoff: Slightly longer startup time before recording
# If false: Keep SDR session open between recordings to reduce startup time
#   Benefits: Faster time to record; maintains stable operating temperature
#   Tradeoff: Higher continuous energy consumption and device heat
#   Warning: When this is off, do not unplug the SDR/USB while active; the application cannot reconnect
shutdown_after_recording = true

# =============================================================================
# VISUALIZATION CONFIGURATION
# =============================================================================

[visualization]
# Enable drawing of amateur radio band markers on spectrum plots
draw_bandplan = true

# Enable drawing of MHz frequency separators on spectrum plots
draw_mhz_separators = true

# PNG compression level (0-9): 0=no compression, 9=maximum compression
# Higher values = smaller files but slower saving
png_compression_level = 6

# FFT decimation method for waterfall plots
# "mean" - Takes average of decimated bins (smoothest appearance, good for noise floor)
# "max" - Takes maximum of decimated bins (preserves narrow band signals and peaks)
# "sample" - Simple sampling (fastest, may miss signals)
decimation_method = "mean"

# Skip image generation for faster processing (data-only mode)
# If true: Only RMS analysis is performed, no spectrum plots are generated
# If false: Full processing including spectrum plot generation
# Useful for high-frequency monitoring where only CSV data is needed
skip_image_generation = false

[visualization.grid]
# Grid row sorting order (true = latest first, false = oldest first)
sort_latest_first = true

# Split daily grids into multiple images by fixed hour windows
# Example: time_window_hours = 6  -> 00-06, 06-12, 12-18, 18-24
# Example: time_window_hours = 12 -> 00-12, 12-24
# Note: Changing this setting during a day will produce mixed windows for that date (old and new labels).
#       To avoid confusion, change it at the start of a new day.
time_window_hours = 12

# Maximum number of recordings to include in grid (0 = unlimited)
# Useful for short interval monitoring sessions - shows only most recent N recordings
max_rows = 0

# Show grid title label (date) in top-left tile
# If true: Date label appears in top-left corner of the grid
# If false: No title label, grid starts directly with frequency labels
show_title_label = true

[visualization.timeslice]
# Limit of most recent days to include in time-slice grids (null = all days)
# Static setting (not user-editable in UI)
days_back = 60

# Hours (0-23) for which time-slice grids are generated after matching recordings
# Dynamic setting (stored in config-dynamic.json); this is the default
hours_default = [6, 12, 18]

# Auto-generate time-slice grids after matching hourly recordings
# Dynamic setting (stored in config-dynamic.json); this is the default
autogenerate_default = false

# =============================================================================
# WEB SERVER CONFIGURATION
# =============================================================================

[web]
# Web server host and port settings
# Default: 'localhost' - Only accessible from local machine
# For network access: Use '0.0.0.0' to bind to all interfaces
# WARNING: Using '0.0.0.0' makes the server accessible to anyone on your network.
#          Only use this on trusted networks as there is no authentication.
# Examples:
#   host = 'localhost'     # Local access only (secure)
#   host = '0.0.0.0'       # Network access (SECURITY RISK on untrusted networks)
#   host = '192.168.1.100' # Specific IP address
host = "localhost"
port = 7060

# Static file cache control (seconds)
# Sets Cache-Control: public, max-age=<value> for Bottle static_file responses.
# Set to 0 to disable caching (no-store).
static_cache_max_age_sec = 0
"""
