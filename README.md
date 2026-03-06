# wordCensor

A Windows desktop tool for blurring sensitive information (emails, names, personal data) in screen recordings.

## Features

- Draw blur regions on any frame of a video
- Automatic tracking using phase correlation + Lucas-Kanade optical flow
- Backward tracking support
- Set start/end frames per region
- Manual correction keyframes
- Feathered Gaussian blur
- Export to MP4 with original audio preserved (via FFmpeg)

## Requirements

- Python 3.10+
- FFmpeg — place `ffmpeg.exe` in a `ffmpeg/` folder next to the project root, or have it on your system PATH

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
python app/main.py
```

Or double-click `dev_run.bat` on Windows.

## Usage

1. Open a video file
2. Draw a rectangle over the area you want to blur
3. Step through frames — tracking updates automatically
4. Use **Correct Position** to fix drift at any frame
5. Use **Set Start Here / Set End Here** to control the blur region's active range
6. Click **Export MP4** when done

## Project Structure

```
app/
  main.py               # Entry point
  core/
    region.py           # BlurRegion data model
    tracker.py          # Phase correlation + LK optical flow tracker
    blurrer.py          # Feathered Gaussian blur
    exporter.py         # FFmpeg pipe-based video export
  ui/
    main_window.py      # Main application window
    video_canvas.py     # Video display + region drawing widget
    timeline_markers.py # Timeline bar showing region spans
```
