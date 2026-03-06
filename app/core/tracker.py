import cv2
import numpy as np

TEMPLATE_PADDING = 60


class RegionTracker:
    def __init__(self):
        self.lk_params = dict(
            winSize=(31, 31),
            maxLevel=4,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.001),
        )
        # Phase correlation confidence threshold.
        # Static frames → conf=1.0, scrolling frames → conf~0.65-0.70
        self.phase_conf_threshold = 0.15

        self.template_threshold = 0.50
        self.template_threshold_global = 0.45
        self.template_search_margin = 300

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_points(self, gray_frame, rect):
        """Sample a grid of feature points inside the rect."""
        x, y, w, h = rect
        margin = 6
        x1, y1 = x + margin, y + margin
        x2, y2 = x + w - margin, y + h - margin

        if x2 <= x1 or y2 <= y1:
            pts = np.array([[x + w / 2, y + h / 2]], dtype=np.float32)
            return pts.reshape(-1, 1, 2)

        cols = max(3, min(6, w // 20))
        rows = max(3, min(6, h // 20))
        xs = np.linspace(x1, x2, cols)
        ys = np.linspace(y1, y2, rows)
        points = np.array([[xi, yi] for yi in ys for xi in xs], dtype=np.float32)
        return points.reshape(-1, 1, 2)

    def get_template(self, gray_frame, rect):
        """
        Extract a padded grayscale template for robust matching.
        Returns (template, (pad_left, pad_top)).
        """
        x, y, w, h = rect
        fh, fw = gray_frame.shape
        p = TEMPLATE_PADDING

        x1 = max(0, x - p)
        y1 = max(0, y - p)
        x2 = min(fw, x + w + p)
        y2 = min(fh, y + h + p)

        if x2 <= x1 or y2 <= y1:
            return None, (0, 0)

        template = gray_frame[y1:y2, x1:x2].copy()
        return template, (x - x1, y - y1)

    def track(self, prev_gray, curr_gray, prev_points, prev_rect,
              template=None, template_offset=(0, 0)):
        """
        Tracking strategy:
          1. Phase correlation  — global frame translation, robust on any region size.
                                  Works perfectly for page scrolling.
          2. LK sparse grid     — fallback when phase correlation confidence is low.
          3. Template match      — local area search.
          4. Template global     — full-frame vertical search.
          5. Hold position       — last resort.

        Returns (new_rect, new_points, success).
        """
        # 1 — Phase correlation (primary, immune to text periodicity & region size)
        motion = self._phase_correlate(prev_gray, curr_gray)
        if motion is not None:
            dx, dy = motion
            x, y, w, h = prev_rect
            new_rect = (int(round(x + dx)), int(round(y + dy)), w, h)
            new_points = self.init_points(curr_gray, new_rect)
            return new_rect, new_points, True

        # 2 — LK on dense grid (handles small local motion when phase fails)
        motion = self._lk_global_motion(prev_gray, curr_gray)
        if motion is not None:
            dx, dy = motion
            x, y, w, h = prev_rect
            new_rect = (int(round(x + dx)), int(round(y + dy)), w, h)
            new_points = self.init_points(curr_gray, new_rect)
            return new_rect, new_points, True

        if template is not None:
            # 3 — Local template match
            matched = self._template_match(
                curr_gray, template, prev_rect, template_offset,
                self.template_threshold
            )
            if matched:
                new_points = self.init_points(curr_gray, matched)
                return matched, new_points, True

            # 4 — Global vertical search
            matched = self._template_match_global(
                curr_gray, template, prev_rect, template_offset
            )
            if matched:
                new_points = self.init_points(curr_gray, matched)
                return matched, new_points, True

        # 5 — Hold
        return prev_rect, prev_points, True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _phase_correlate(self, prev_gray, curr_gray):
        """
        Use OpenCV phase correlation to measure the global frame translation.
        Runs at 25% resolution for ~16x speedup — accurate enough for scroll
        estimation, since we only need the translation vector, not pixel precision.
        Returns (dx, dy) scaled back to full resolution, or None.
        """
        scale = 0.5
        small_prev = cv2.resize(prev_gray, None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_AREA).astype(np.float32)
        small_curr = cv2.resize(curr_gray, None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_AREA).astype(np.float32)

        (dx, dy), response = cv2.phaseCorrelate(small_prev, small_curr)

        if response >= self.phase_conf_threshold:
            return (dx / scale, dy / scale)
        return None

    def _lk_global_motion(self, prev_gray, curr_gray):
        """
        Sparse LK on a dense grid of points spread across the whole frame.
        Fallback when phase correlation confidence is too low.
        Returns median (dx, dy) or None.
        """
        h, w = prev_gray.shape
        cols, rows = 12, 9
        xs = np.linspace(w * 0.05, w * 0.95, cols)
        ys = np.linspace(h * 0.05, h * 0.95, rows)
        pts = np.array([[xi, yi] for yi in ys for xi in xs], dtype=np.float32)
        pts = pts.reshape(-1, 1, 2)

        next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
            prev_gray, curr_gray, pts, None, **self.lk_params
        )

        if next_pts is None or status is None:
            return None

        good_prev = pts[status.ravel() == 1]
        good_next = next_pts[status.ravel() == 1]

        if len(good_next) < 6:
            return None

        dx = float(np.median(good_next[:, 0, 0] - good_prev[:, 0, 0]))
        dy = float(np.median(good_next[:, 0, 1] - good_prev[:, 0, 1]))

        return (dx, dy)

    def _template_match(self, gray, template, hint_rect, template_offset, threshold):
        if template is None:
            return None

        th, tw = template.shape[:2]
        fh, fw = gray.shape
        pad_left, pad_top = template_offset
        x, y, rw, rh = hint_rect

        m = self.template_search_margin
        sx1 = max(0, x - m)
        sy1 = max(0, y - m)
        sx2 = min(fw, x + rw + m)
        sy2 = min(fh, y + rh + m)

        search = gray[sy1:sy2, sx1:sx2]
        if search.shape[0] < th or search.shape[1] < tw:
            return None

        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            mx, my = max_loc
            return (sx1 + mx + pad_left, sy1 + my + pad_top, rw, rh)

        return None

    def _template_match_global(self, gray, template, hint_rect, template_offset):
        if template is None:
            return None

        th, tw = template.shape[:2]
        fh, fw = gray.shape
        pad_left, pad_top = template_offset
        x, y, rw, rh = hint_rect

        horiz_margin = fw // 2
        sx1 = max(0, x - horiz_margin)
        sx2 = min(fw, x + rw + horiz_margin)
        search = gray[0:fh, sx1:sx2]

        if search.shape[0] < th or search.shape[1] < tw:
            return None

        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= self.template_threshold_global:
            mx, my = max_loc
            return (sx1 + mx + pad_left, my + pad_top, rw, rh)

        return None
