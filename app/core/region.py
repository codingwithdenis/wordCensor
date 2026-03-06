class BlurRegion:
    _next_id = 0

    def __init__(self, start_frame, rect, color=(255, 100, 0)):
        self.id = BlurRegion._next_id
        BlurRegion._next_id += 1
        self.start_frame = start_frame
        self.color = color
        self.template = None          # padded grayscale patch for template matching
        self.template_offset = (0, 0)  # (pad_left, pad_top) to map match → rect
        self.end_frame = None          # None = track until end of video
        # {frame_idx: {'rect': (x, y, w, h), 'points': np.array or None}}
        self._states = {start_frame: {'rect': rect, 'points': None}}

    def get_rect(self, frame_idx):
        """Return the rect for the given frame, or None if outside active range."""
        if frame_idx < self.start_frame:
            return None
        if self.end_frame is not None and frame_idx > self.end_frame:
            return None
        candidates = [f for f in self._states if f <= frame_idx]
        if not candidates:
            return None
        return self._states[max(candidates)]['rect']

    def get_tracking_state(self, frame_idx):
        """Return the tracking state dict closest to frame_idx (at or before)."""
        candidates = [f for f in self._states if f <= frame_idx]
        if not candidates:
            return None
        return self._states[max(candidates)]

    def get_state_frame(self, frame_idx):
        """Return the actual frame index of the closest stored state."""
        candidates = [f for f in self._states if f <= frame_idx]
        if not candidates:
            return None
        return max(candidates)

    def has_state_at(self, frame_idx):
        return frame_idx in self._states

    def set_tracking_state(self, frame_idx, rect, points):
        self._states[frame_idx] = {'rect': rect, 'points': points}

    def clear_states_after(self, frame_idx):
        """Remove all tracked states after a given frame (used on manual correction)."""
        to_remove = [f for f in self._states if f > frame_idx]
        for f in to_remove:
            del self._states[f]
