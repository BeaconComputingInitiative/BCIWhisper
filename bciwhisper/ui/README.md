# UI layer

UI is the highest layer and may depend on every lower layer.

Target grouping:

- main_window.py
- boot_screen.py
- monitor_tab.py
- recordings_tab.py
- transcripts_tab.py
- stream_tab.py
- mastering_tab.py

The UI must not:
- enumerate/open microphones;
- own DSP filter state;
- write SQLite directly;
- manage Whisper engines directly;
- spawn Bun except through the broadcast process manager.
