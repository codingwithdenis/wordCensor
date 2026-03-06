import cv2
import subprocess
import numpy as np
from core.blurrer import apply_blur


def export_video(input_path, output_path, regions, tracker, ffmpeg_path, progress_callback=None):
    """
    Export video with all blur regions applied.
    Uses FFmpeg via stdin pipe — no temp files needed.
    Audio is copied from the original file.
    """
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # FFmpeg command: read raw BGR frames from stdin, mux with original audio.
    # -loglevel error suppresses the verbose progress output that would fill
    # the stderr pipe buffer and cause a deadlock during the write loop.
    cmd = [
        ffmpeg_path, '-y',
        '-loglevel', 'error',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-s', f'{width}x{height}',
        '-pix_fmt', 'bgr24',
        '-r', str(fps),
        '-i', 'pipe:0',
        '-i', input_path,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '18',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-map', '0:v:0',
        '-map', '1:a:0?',   # optional — skip if no audio track
        '-shortest',
        output_path,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        raise RuntimeError(
            f"FFmpeg not found at '{ffmpeg_path}'.\n"
            "Place ffmpeg.exe in the ffmpeg/ folder next to the app."
        )

    # Per-region export tracking state (independent of the UI state)
    export_state = {}
    for region in regions:
        export_state[region.id] = {'rect': None, 'points': None}

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    prev_gray = None

    try:
        for frame_idx in range(total_frames):
            ret, frame = cap.read()
            if not ret:
                break

            curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            active_rects = []

            for region in regions:
                state = export_state[region.id]

                if frame_idx == region.start_frame:
                    # Initialize from the user-drawn rect
                    rect = region.get_rect(frame_idx)
                    if rect is None:
                        continue
                    points = tracker.init_points(curr_gray, rect)
                    state['rect'] = rect
                    state['points'] = points

                elif frame_idx > region.start_frame and prev_gray is not None:
                    if state['rect'] is not None:
                        # If user set a manual keyframe here, use it
                        state_frame = region.get_state_frame(frame_idx)
                        if state_frame == frame_idx:
                            rect = region.get_rect(frame_idx)
                            if rect is None:
                                continue
                            points = tracker.init_points(curr_gray, rect)
                            state['rect'] = rect
                            state['points'] = points
                        else:
                            # Track forward with LK + template fallback
                            new_rect, new_points, ok = tracker.track(
                                prev_gray, curr_gray,
                                state['points'], state['rect'],
                                template=region.template,
                                template_offset=region.template_offset
                            )
                            state['rect'] = new_rect
                            if new_points is not None:
                                state['points'] = new_points

                if (state['rect'] is not None
                        and frame_idx >= region.start_frame
                        and (region.end_frame is None or frame_idx <= region.end_frame)):
                    active_rects.append(state['rect'])

            blurred = apply_blur(frame, active_rects)

            try:
                proc.stdin.write(blurred.tobytes())
            except BrokenPipeError:
                break

            prev_gray = curr_gray

            if progress_callback:
                progress_callback(frame_idx + 1, total_frames)

    finally:
        cap.release()
        try:
            proc.stdin.close()
        except Exception:
            pass
        _, stderr = proc.communicate()
        if proc.returncode not in (0, None):
            raise RuntimeError(f"FFmpeg error:\n{stderr.decode(errors='replace')}")
