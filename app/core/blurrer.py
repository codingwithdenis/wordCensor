import cv2
import numpy as np

# Pixels of soft feather fade at each edge of the blur box.
FEATHER_RADIUS = 2


def apply_blur(frame, rects, kernel_size=61):
    """
    Apply feathered Gaussian blur to all given rects on the frame.

    Off-screen check: if the region center is outside the frame, skip it entirely.
    This prevents tracked regions from blurring fixed UI elements (taskbar, chrome)
    after the tracked content has scrolled off screen.

    Feather: a smooth gradient mask fades the blur to transparent at the edges,
    so the blur box blends naturally instead of having a hard rectangular cut.
    """
    result = frame.copy()
    h, w = frame.shape[:2]
    k = kernel_size if kernel_size % 2 == 1 else kernel_size + 1

    for rect in rects:
        x, y, rw, rh = rect

        # --- Off-screen guard ---
        # If the center of the region is outside the frame, the tracked content
        # has scrolled away. Skip to avoid blurring unrelated UI elements.
        cx = x + rw / 2
        cy = y + rh / 2
        if cx < 0 or cx >= w or cy < 0 or cy >= h:
            continue

        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(w, x + rw)
        y2 = min(h, y + rh)

        if x2 <= x1 or y2 <= y1:
            continue

        clip_h = y2 - y1
        clip_w = x2 - x1

        roi = result[y1:y2, x1:x2]
        blurred = cv2.GaussianBlur(roi, (k, k), 0)

        # --- Feathered blend ---
        # Build a solid white rectangle, blur it to get smooth gradient edges,
        # then use it as an alpha mask to blend blurred over original.
        f = min(FEATHER_RADIUS, clip_h // 4, clip_w // 4)
        if f > 0:
            mask = np.zeros((clip_h, clip_w), dtype=np.float32)
            mask[f: clip_h - f, f: clip_w - f] = 1.0
            blur_k = f * 2 + 1
            mask = cv2.GaussianBlur(mask, (blur_k, blur_k), f / 2.0)
            mask3 = mask[:, :, np.newaxis]
            blended = (blurred.astype(np.float32) * mask3
                       + roi.astype(np.float32) * (1.0 - mask3))
            result[y1:y2, x1:x2] = blended.astype(np.uint8)
        else:
            result[y1:y2, x1:x2] = blurred

    return result
