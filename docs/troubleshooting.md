
### Common Issues

#### SDR Device Not Detected

You should see this output when starting a record process:
```bash
Using device #0 RTLSDRBlog Blog V4 SN: 00000001
Found Rafael Micro R828D tuner
RTL-SDR Blog V4 Detected
```
Windows: make sure to install the RTL-SDR v4 drivers via Zadig.

#### Windows: Application quits when initializing the SDR
I observed this behaviour a few times with RTLSDR on Windows. The application silently exits after this output:

```
gr-osmosdr 0.2.0.0 (0.2.0) gnuradio 3.10.12.0
built-in source types: file rtl rtl_tcp uhd miri hackrf bladerf airspy airspyhf soapy redpitaya
[INFO] [UHD] Win32; Microsoft Visual C++ version 14.2; Boost_108600; UHD_4.8.0.0-release
```

This never happens on Raspberry Pi Linux. Not sure about the reason. You can try disabling `sdr_shutdown_after_recording` (keep SDR running between recordings) and see if it helps.


#### SDR disconnected during recording

If the SDR is unplugged or drops off the USB bus while recording, the recording
first stalls and the application may then exit:

```
2026-08-11 13:55:55,905 - root - INFO - Record 30m | center_frequency=10100 kHz | span=2400 kHz | duration=2.0 s
cb transfer status: 4, canceling...
cb transfer status: 5, canceling...
rtlsdr_read_async returned with -5
```

The device stops delivering samples without reporting an error to the application,
so the running capture never finishes on its own. A timeout ends it after the
recording duration plus `capture_timeout_margin_sec` (see `config-static.toml`),
logs `SDR delivered no data for ... - device stalled or disconnected`, and aborts
the remaining captures of that run.

Shutting the SDR down afterwards can then terminate the process without any
further log output. The cause is in the RTL-SDR driver: after the USB device is
gone, librtlsdr still cleans up its transfer buffers and crashes. This cannot be
caught by the application, since it happens in native code, not in Python.

I observed this with RTLSDR on Windows. SDRplay uses a separate API service
process for the USB communication, so it is likely to behave differently there.

The SDR cannot be reconnected without restarting the application. On Raspberry Pi
the systemd service (`Restart=always`) starts it again automatically, so the next
scheduled recording runs as usual. Windows has no systemd equivalent, but a small
batch file that starts `main.py` in an endless loop does the same job: the crash
only ends the process, so the loop starts it again.

If this happens without anyone touching the hardware, suspect USB power: a weak
supply or a long/thin cable can make the dongle drop off the bus under load.


#### Application crashes with OutOfMemory Error

Each frequency slice is recorded in memory and written to disk after recording is completed. 
This is to prevent performance problems on computers with slow IO. Reduce recording time and / or FFT size.


#### Web Interface Not Accessible
- Ensure no firewall is blocking port 7060
- Check if the application started successfully in the terminal
- Try accessing `http://127.0.0.1:7060` instead of localhost


#### Performance Issues
- Reduce FFT size via the web interface for faster processing
- Lower the span or recording time for less CPU usage
