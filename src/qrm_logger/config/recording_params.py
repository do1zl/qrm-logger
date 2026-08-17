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
Recording and FFT parameter configuration for QRM Logger.
Contains timing settings, FFT processing parameters, and signal analysis configuration.
"""

from .toml_config import _toml

# =============================================================================
# RECORDING PARAMETERS
# =============================================================================

# Recording time in seconds
# dynamic property, managed by config-dynamic.json
rec_time_default_sec = _toml["recording"]["rec_time_default_sec"]

# Frame rate for GNU Radio processing
frame_rate_default = _toml["recording"]["frame_rate_default"]

# wait time after changing the frequency
# Recommended values: RTLSDR 0.5, SDRplay 2
frequency_change_delay_sec = _toml["recording"]["frequency_change_delay_sec"]

# Extra time granted to a capture run on top of its recording duration before the
# SDR is considered stalled. A device that disappears mid-recording (USB unplug,
# driver error) stops delivering samples without raising anything, so this timeout
# is the only way the recording loop notices.
capture_timeout_margin_sec = _toml["recording"].get("capture_timeout_margin_sec", 10)

# =============================================================================
# FFT CONFIGURATION
# =============================================================================

# Spectrum range configuration for plot generation
# Used to set the dB scale limits on generated spectrum plots
# dynamic property, managed by config-dynamic.json
min_db = _toml["recording"]["fft"]["min_db"]  # Minimum dB level for spectrum plots
# dynamic property, managed by config-dynamic.json
max_db = _toml["recording"]["fft"]["max_db"]  # Maximum dB level for spectrum plots

# FFT size for spectrum analysis (must be power of 2)
# Higher values = better frequency resolution but slower processing
# Common values: 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072
# dynamic property, managed by config-dynamic.json (maps to 'fft_size')
fft_size_default = _toml["recording"]["fft"]["fft_size_default"]

# FFT Smoothing/Averaging Configuration
# avg_alpha controls exponential averaging of FFT data (0.0 to 1.0)
# 1.0 = no averaging (raw FFT data)
# 0.1 = heavy smoothing, 0.5 = moderate smoothing, 0.9 = light smoothing
fft_avg_alpha = _toml["recording"]["fft"]["fft_avg_alpha"]
