import os
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QFileDialog,
    QListWidget, QListWidgetItem, QProgressDialog,
    QMessageBox, QFrame, QShortcut, QSizePolicy,
    QStatusBar, QStyledItemDelegate, QStyle,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QRect
from PyQt5.QtGui import QColor, QKeySequence, QFont

from ui.video_canvas import VideoCanvas
from ui.timeline_markers import TimelineMarkers
from core.region import BlurRegion
from core.tracker import RegionTracker
from core.blurrer import apply_blur
from core.exporter import export_video

# ------------------------------------------------------------------
# Background export worker
# ------------------------------------------------------------------

class ExportWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, video_path, out_path, regions, tracker, ffmpeg_path):
        super().__init__()
        self.video_path = video_path
        self.out_path = out_path
        self.regions = regions
        self.tracker = tracker
        self.ffmpeg_path = ffmpeg_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        def on_progress(current, total):
            if self._cancelled:
                raise InterruptedError("Export cancelled.")
            self.progress.emit(current, total)

        try:
            export_video(
                self.video_path, self.out_path,
                self.regions, self.tracker,
                self.ffmpeg_path, on_progress
            )
            if not self._cancelled:
                self.finished.emit(self.out_path)
        except InterruptedError:
            pass
        except Exception as e:
            self.error.emit(str(e))


# Colors — fully saturated, evenly spaced around the hue wheel for max distinction
REGION_COLORS = [
    (255,  50,  50),   # red
    (50,  220,  50),   # green
    (80,  140, 255),   # blue
    (255, 210,   0),   # yellow
    (0,   220, 220),   # cyan
    (220,   0, 220),   # magenta
    (255, 130,   0),   # orange
    (160,   0, 255),   # purple
    (0,   200, 120),   # teal
    (255,  80, 160),   # pink
]


class RegionItemDelegate(QStyledItemDelegate):
    """Custom painter for blur region list items.

    Each row shows:
      • A solid color strip on the left (thicker when selected)
      • Region name on the first line (bold when selected)
      • Frame range on the second line in smaller text
    """

    ROW_H = 46
    STRIP_W = 6
    STRIP_W_SEL = 8

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        is_selected = bool(option.state & QStyle.State_Selected)

        color_data = index.data(Qt.UserRole + 1)
        r, g, b = color_data if color_data else (120, 120, 120)
        color = QColor(r, g, b)

        # Background
        if is_selected:
            painter.fillRect(rect, QColor(r // 3, g // 3, b // 3))
        else:
            painter.fillRect(rect, QColor(28, 28, 28))

        # Bottom separator line
        painter.setPen(QColor(50, 50, 50))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        # Left color strip
        sw = self.STRIP_W_SEL if is_selected else self.STRIP_W
        painter.fillRect(rect.x(), rect.y(), sw, rect.height(), color)

        # Text area
        tx = rect.x() + sw + 9
        tw = rect.width() - sw - 12

        # Line 1: region name
        full_text = index.data(Qt.DisplayRole) or ""
        parts = full_text.split("  [", 1)
        name = parts[0]
        frames = ("[" + parts[1]) if len(parts) > 1 else ""

        name_font = QFont()
        name_font.setPointSize(9)
        name_font.setBold(is_selected)
        painter.setFont(name_font)
        painter.setPen(QColor(255, 255, 255) if is_selected else color)
        name_rect = QRect(tx, rect.y() + 6, tw, 18)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, name)

        # Line 2: frame range
        frame_font = QFont()
        frame_font.setPointSize(7)
        painter.setFont(frame_font)
        painter.setPen(QColor(210, 210, 210) if is_selected else QColor(110, 110, 110))
        frame_rect = QRect(tx, rect.y() + 24, tw, 14)
        painter.drawText(frame_rect, Qt.AlignLeft | Qt.AlignVCenter, frames)

        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("wordCensor")
        self.resize(1280, 720)

        # Video state
        self.cap = None
        self.video_path = None
        self.total_frames = 0
        self.fps = 30.0
        self.current_frame_idx = 0
        self.prev_frame_idx = -1
        self.prev_gray = None
        self.current_frame_bgr = None

        # Regions
        self.regions = []
        self.tracker = RegionTracker()
        self._correction_mode = False   # True only when user clicked "Correct"

        # Playback
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._on_play_tick)
        self.is_playing = False

        self._build_ui()
        self._build_shortcuts()
        self._find_ffmpeg()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Left: video + controls ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        # Toolbar
        tb = QWidget()
        tb_layout = QHBoxLayout(tb)
        tb_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_open = QPushButton("Open Video")
        self.btn_open.setFixedHeight(32)
        self.btn_open.clicked.connect(self._open_video)

        self.btn_export = QPushButton("Export MP4")
        self.btn_export.setFixedHeight(32)
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)

        self.lbl_file = QLabel("No video loaded")
        self.lbl_file.setStyleSheet("color: #888888; font-size: 11px;")

        tb_layout.addWidget(self.btn_open)
        tb_layout.addWidget(self.btn_export)
        tb_layout.addSpacing(12)
        tb_layout.addWidget(self.lbl_file)
        tb_layout.addStretch()
        left_layout.addWidget(tb)

        # Canvas
        self.canvas = VideoCanvas()
        self.canvas.region_drawn.connect(self._on_region_drawn)
        left_layout.addWidget(self.canvas, 1)

        # Timeline markers bar
        self.timeline_markers = TimelineMarkers()
        left_layout.addWidget(self.timeline_markers)

        # Timeline slider
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.setSingleStep(1)
        self.slider.valueChanged.connect(self._on_slider_changed)
        left_layout.addWidget(self.slider)

        # Playback controls
        ctl = QWidget()
        ctl_layout = QHBoxLayout(ctl)
        ctl_layout.setContentsMargins(0, 0, 0, 0)
        ctl_layout.setSpacing(4)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(36, 30)
        self.btn_prev.setToolTip("Previous frame  [←]")
        self.btn_prev.clicked.connect(self._prev_frame)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(48, 30)
        self.btn_play.setToolTip("Play / Pause  [Space]")
        self.btn_play.clicked.connect(self._toggle_play)

        self.btn_next = QPushButton("▶|")
        self.btn_next.setFixedSize(36, 30)
        self.btn_next.setToolTip("Next frame  [→]")
        self.btn_next.clicked.connect(self._next_frame)

        self.lbl_frame = QLabel("— / —")
        self.lbl_frame.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_frame.setStyleSheet("font-size: 12px; color: #cccccc; min-width: 90px;")

        ctl_layout.addWidget(self.btn_prev)
        ctl_layout.addWidget(self.btn_play)
        ctl_layout.addWidget(self.btn_next)
        ctl_layout.addStretch()
        ctl_layout.addWidget(self.lbl_frame)
        left_layout.addWidget(ctl)

        root.addWidget(left, 1)

        # ---- Right: regions panel ----
        right = QFrame()
        right.setFrameShape(QFrame.StyledPanel)
        right.setFixedWidth(240)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(6)

        right_layout.addWidget(QLabel("<b>Blur Regions</b>"))

        self.region_list = QListWidget()
        self.region_list.setAlternatingRowColors(False)
        self.region_list.setItemDelegate(RegionItemDelegate(self.region_list))
        self.region_list.setStyleSheet(
            "QListWidget { background: #1c1c1c; border: 1px solid #333; }"
            "QListWidget::item { border: none; }"
            "QListWidget::item:selected { background: transparent; }"
        )
        self.region_list.currentItemChanged.connect(self._on_region_selection_changed)
        right_layout.addWidget(self.region_list, 1)

        # Mode indicator — shows when a region is selected for correction
        self.lbl_mode = QLabel("")
        self.lbl_mode.setWordWrap(True)
        self.lbl_mode.setStyleSheet(
            "color: #ffcc00; font-size: 11px; padding: 4px;"
            "border: 1px solid #665500; border-radius: 3px;"
        )
        self.lbl_mode.hide()
        right_layout.addWidget(self.lbl_mode)

        self.btn_correct = QPushButton("Correct Position")
        self.btn_correct.setToolTip(
            "Activate correction mode for the selected region.\n"
            "Then draw a new rectangle to reposition it at this frame."
        )
        self.btn_correct.setCheckable(True)
        self.btn_correct.setEnabled(False)
        self.btn_correct.clicked.connect(self._toggle_correction_mode)
        right_layout.addWidget(self.btn_correct)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color: #444;")
        right_layout.addWidget(sep1)

        # End frame controls
        end_row = QWidget()
        end_layout = QHBoxLayout(end_row)
        end_layout.setContentsMargins(0, 0, 0, 0)
        end_layout.setSpacing(4)

        self.btn_set_start = QPushButton("Set Start Here")
        self.btn_set_start.setToolTip("Start tracking this region from the current frame")
        self.btn_set_start.clicked.connect(self._set_start_frame)
        self.btn_set_start.setEnabled(False)

        self.btn_set_end = QPushButton("Set End Here")
        self.btn_set_end.setToolTip("Stop tracking this region at the current frame")
        self.btn_set_end.clicked.connect(self._set_end_frame)
        self.btn_set_end.setEnabled(False)

        end_layout.addWidget(self.btn_set_start)
        end_layout.addWidget(self.btn_set_end)
        right_layout.addWidget(end_row)

        self.btn_delete = QPushButton("Delete Selected  [Del]")
        self.btn_delete.clicked.connect(self._delete_selected_region)
        right_layout.addWidget(self.btn_delete)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #444;")
        right_layout.addWidget(sep2)

        hint = QLabel(
            "Draw on video to add region.\n"
            "Select a region, then draw\n"
            "to correct its position.\n\n"
            "Shortcuts:\n"
            "  Space — play / pause\n"
            "  ← → — step frames\n"
            "  Del — delete region"
        )
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        right_layout.addWidget(hint)

        root.addWidget(right)

        self.statusBar().showMessage("Open a video file to start.")

    def _build_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Space), self).activated.connect(self._toggle_play)
        QShortcut(QKeySequence(Qt.Key_Left), self).activated.connect(self._prev_frame)
        QShortcut(QKeySequence(Qt.Key_Right), self).activated.connect(self._next_frame)
        QShortcut(QKeySequence(Qt.Key_Delete), self).activated.connect(self._delete_selected_region)

    def _find_ffmpeg(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled = os.path.normpath(os.path.join(base, '..', 'ffmpeg', 'ffmpeg.exe'))
        if os.path.exists(bundled):
            self.ffmpeg_path = bundled
        else:
            self.ffmpeg_path = 'ffmpeg'

    # ------------------------------------------------------------------
    # Video loading
    # ------------------------------------------------------------------

    def _open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.webm)"
        )
        if not path:
            return

        if self.cap:
            self.cap.release()

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            QMessageBox.critical(self, "Error", "Could not open video file.")
            self.cap = None
            return

        self.video_path = path
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0

        self.regions = []
        BlurRegion._next_id = 0
        self.region_list.clear()
        self.current_frame_idx = 0
        self.prev_frame_idx = -1
        self.prev_gray = None
        self.current_frame_bgr = None

        self.slider.blockSignals(True)
        self.slider.setMaximum(max(0, self.total_frames - 1))
        self.slider.setValue(0)
        self.slider.blockSignals(False)

        self.btn_export.setEnabled(True)
        self.lbl_file.setText(os.path.basename(path))
        self.statusBar().showMessage(
            f"Loaded: {os.path.basename(path)}  |  "
            f"{self.total_frames} frames  |  {self.fps:.2f} fps"
        )

        self._show_frame(0)

    # ------------------------------------------------------------------
    # Frame display & tracking
    # ------------------------------------------------------------------

    def _show_frame(self, idx):
        if not self.cap:
            return

        idx = max(0, min(idx, self.total_frames - 1))
        # Skip the costly seek when advancing exactly one frame forward —
        # the decoder is already positioned there during sequential playback.
        if idx != self.current_frame_idx + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = self.cap.read()
        if not ret:
            return

        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        stepping_forward = (idx == self.prev_frame_idx + 1 and self.prev_gray is not None)
        stepping_backward = (idx == self.prev_frame_idx - 1 and self.prev_gray is not None)

        if stepping_forward or stepping_backward:
            for region in self.regions:
                # Skip if we already have a tracked state at the target frame
                if region.has_state_at(idx):
                    continue

                # For forward: skip if region hasn't started yet or already ended
                if stepping_forward:
                    if region.start_frame > self.prev_frame_idx:
                        continue
                    if region.end_frame is not None and self.prev_frame_idx >= region.end_frame:
                        continue

                # For backward: skip if region has no state to work from
                if stepping_backward:
                    if not region.has_state_at(self.prev_frame_idx):
                        continue

                prev_state = region.get_tracking_state(self.prev_frame_idx)
                if prev_state is None:
                    continue

                rect = prev_state['rect']
                points = prev_state['points']

                state_frame = region.get_state_frame(self.prev_frame_idx)
                if state_frame != self.prev_frame_idx or points is None:
                    points = self.tracker.init_points(self.prev_gray, rect)

                # phaseCorrelate(prev, curr) works for both directions:
                # forward: prev=frame_N, curr=frame_N+1 → positive scroll motion
                # backward: prev=frame_N, curr=frame_N-1 → negative/reverse motion
                new_rect, new_points, ok = self.tracker.track(
                    self.prev_gray, curr_gray, points, rect,
                    template=region.template,
                    template_offset=region.template_offset
                )

                # When tracking backwards before the region's start, extend it
                if stepping_backward and idx < region.start_frame:
                    region.start_frame = idx

                region.set_tracking_state(
                    idx, new_rect, new_points if new_points is not None else points
                )

        self.current_frame_bgr = frame
        self.prev_gray = curr_gray
        self.prev_frame_idx = idx
        self.current_frame_idx = idx

        self._refresh_canvas(frame, idx)
        self._update_timeline()

        self.lbl_frame.setText(f"{idx + 1} / {self.total_frames}")
        self.slider.blockSignals(True)
        self.slider.setValue(idx)
        self.slider.blockSignals(False)

    def _refresh_canvas(self, frame, frame_idx):
        selected = self._get_selected_region()
        selected_id = selected.id if selected else None
        display_regions = []
        for i, region in enumerate(self.regions):
            rect = region.get_rect(frame_idx)
            if rect:
                display_regions.append((rect, region.color, region.id, f"R{region.id + 1}"))
        self.canvas.set_frame(frame, display_regions, selected_id)

    def _update_timeline(self):
        self.timeline_markers.update_state(
            self.total_frames, self.regions, self.current_frame_idx
        )

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    def _toggle_play(self):
        if not self.cap:
            return
        if self.is_playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self):
        interval = max(1, int(1000 / self.fps))
        self.play_timer.start(interval)
        self.btn_play.setText("⏸")
        self.is_playing = True

    def _stop_play(self):
        self.play_timer.stop()
        self.btn_play.setText("▶")
        self.is_playing = False

    def _on_play_tick(self):
        if self.current_frame_idx >= self.total_frames - 1:
            self._stop_play()
            return
        self._show_frame(self.current_frame_idx + 1)

    def _prev_frame(self):
        if self.is_playing:
            self._stop_play()
        self._show_frame(self.current_frame_idx - 1)

    def _next_frame(self):
        if self.is_playing:
            self._stop_play()
        self._show_frame(self.current_frame_idx + 1)

    def _on_slider_changed(self, value):
        if value == self.current_frame_idx:
            return
        if self.is_playing:
            self._stop_play()
        self.prev_gray = None
        self.prev_frame_idx = value - 1
        self._show_frame(value)

    # ------------------------------------------------------------------
    # Region management
    # ------------------------------------------------------------------

    def _get_selected_region(self):
        """Return the currently selected BlurRegion, or None."""
        item = self.region_list.currentItem()
        if not item:
            return None
        rid = item.data(Qt.UserRole)
        return next((r for r in self.regions if r.id == rid), None)

    def _on_region_selection_changed(self, current, previous):
        # Leaving a region — cancel any active correction mode
        self._exit_correction_mode()

        region = self._get_selected_region()
        if region:
            self.btn_correct.setEnabled(True)
            self.btn_set_start.setEnabled(True)
            self.btn_set_end.setEnabled(True)
        else:
            self.btn_correct.setEnabled(False)
            self.btn_set_start.setEnabled(False)
            self.btn_set_end.setEnabled(False)
            self.lbl_mode.hide()

        # Refresh canvas so the selection highlight updates immediately
        if self.current_frame_bgr is not None:
            self._refresh_canvas(self.current_frame_bgr, self.current_frame_idx)

    def _toggle_correction_mode(self, checked):
        if checked:
            region = self._get_selected_region()
            if not region:
                self.btn_correct.setChecked(False)
                return
            self._correction_mode = True
            r, g, b = region.color
            self.lbl_mode.setText(
                f"Correction mode: Region {region.id + 1}\n"
                "Draw a rectangle to reposition it."
            )
            self.lbl_mode.setStyleSheet(
                f"color: rgb({r},{g},{b}); font-size: 11px; padding: 4px;"
                f"border: 1px solid rgb({r//2},{g//2},{b//2}); border-radius: 3px;"
            )
            self.lbl_mode.show()
            self.statusBar().showMessage(
                f"Correction mode active — draw to reposition Region {region.id + 1}."
            )
        else:
            self._exit_correction_mode()

    def _exit_correction_mode(self):
        self._correction_mode = False
        self.btn_correct.setChecked(False)
        self.lbl_mode.hide()

    def _on_region_drawn(self, rect):
        if not self.cap:
            return
        if self.is_playing:
            self._stop_play()

        if self._correction_mode:
            selected = self._get_selected_region()
            if selected is not None and self.current_frame_idx >= selected.start_frame:
                self._correct_region(selected, rect)
                self._exit_correction_mode()
                return

        self._create_region(rect)

    def _create_region(self, rect):
        color = REGION_COLORS[len(self.regions) % len(REGION_COLORS)]
        region = BlurRegion(
            start_frame=self.current_frame_idx,
            rect=rect,
            color=color,
        )

        if self.current_frame_bgr is not None:
            gray = cv2.cvtColor(self.current_frame_bgr, cv2.COLOR_BGR2GRAY)
            points = self.tracker.init_points(gray, rect)
            region.template, region.template_offset = self.tracker.get_template(gray, rect)
            region.set_tracking_state(self.current_frame_idx, rect, points)

        self.regions.append(region)

        r, g, b = color
        item = QListWidgetItem(self._region_label(region))
        item.setData(Qt.UserRole, region.id)
        item.setData(Qt.UserRole + 1, (r, g, b))
        self.region_list.addItem(item)
        self.region_list.setCurrentItem(item)

        if self.current_frame_bgr is not None:
            self._refresh_canvas(self.current_frame_bgr, self.current_frame_idx)
        self._update_timeline()

        self.statusBar().showMessage(
            f"Region {region.id + 1} added at frame {self.current_frame_idx + 1}."
        )

    def _correct_region(self, region, rect):
        """Apply a manual correction keyframe to an existing region."""
        frame_idx = self.current_frame_idx

        # Discard all tracking states after this frame — they'll be re-tracked
        region.clear_states_after(frame_idx)

        if self.current_frame_bgr is not None:
            gray = cv2.cvtColor(self.current_frame_bgr, cv2.COLOR_BGR2GRAY)
            points = self.tracker.init_points(gray, rect)
            region.template, region.template_offset = self.tracker.get_template(gray, rect)
            region.set_tracking_state(frame_idx, rect, points)

        # Refresh tracking context so the next sequential step uses the corrected position
        self.prev_gray = cv2.cvtColor(self.current_frame_bgr, cv2.COLOR_BGR2GRAY) \
            if self.current_frame_bgr is not None else None
        self.prev_frame_idx = frame_idx

        self._update_region_list_item(region)
        self._refresh_canvas(self.current_frame_bgr, frame_idx)
        self._update_timeline()

        self.statusBar().showMessage(
            f"Region {region.id + 1} corrected at frame {frame_idx + 1}. "
            "Tracking resumes forward from here."
        )

    def _set_end_frame(self):
        region = self._get_selected_region()
        if not region:
            return
        if self.current_frame_idx <= region.start_frame:
            self.statusBar().showMessage("End frame must be after the start frame.")
            return
        region.end_frame = self.current_frame_idx
        self._update_region_list_item(region)
        self._refresh_canvas(self.current_frame_bgr, self.current_frame_idx)
        self._update_timeline()
        self.statusBar().showMessage(
            f"Region {region.id + 1} ends at frame {self.current_frame_idx + 1}."
        )

    def _set_start_frame(self):
        region = self._get_selected_region()
        if not region:
            return
        if region.end_frame is not None and self.current_frame_idx >= region.end_frame:
            self.statusBar().showMessage("Start frame must be before end frame.")
            return
        region.start_frame = self.current_frame_idx
        self._update_region_list_item(region)
        self._refresh_canvas(self.current_frame_bgr, self.current_frame_idx)
        self._update_timeline()
        self.statusBar().showMessage(
            f"Region {region.id + 1} starts at frame {self.current_frame_idx + 1}."
        )

    def _delete_selected_region(self):
        item = self.region_list.currentItem()
        if not item:
            return
        rid = item.data(Qt.UserRole)
        self.regions = [r for r in self.regions if r.id != rid]
        self.region_list.takeItem(self.region_list.row(item))
        if self.current_frame_bgr is not None:
            self._refresh_canvas(self.current_frame_bgr, self.current_frame_idx)
        self._update_timeline()
        self.statusBar().showMessage("Region deleted.")

    def _region_label(self, region):
        label = f"Region {region.id + 1}  [f:{region.start_frame + 1}"
        if region.end_frame is not None:
            label += f"→{region.end_frame + 1}"
        label += "]"
        return label

    def _update_region_list_item(self, region):
        r, g, b = region.color
        for i in range(self.region_list.count()):
            item = self.region_list.item(i)
            if item.data(Qt.UserRole) == region.id:
                item.setText(self._region_label(region))
                item.setData(Qt.UserRole + 1, (r, g, b))
                break

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export(self):
        if not self.video_path:
            return

        if not self.regions:
            QMessageBox.warning(self, "No Regions",
                                "Draw at least one blur region before exporting.")
            return

        base, _ = os.path.splitext(self.video_path)
        suggestion = base + "_censored.mp4"

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Censored Video", suggestion, "MP4 Video (*.mp4)"
        )
        if not out_path:
            return

        self._stop_play()

        progress = QProgressDialog(
            "Exporting video...", "Cancel", 0, self.total_frames, self
        )
        progress.setWindowTitle("Exporting")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        self._export_worker = ExportWorker(
            self.video_path, out_path,
            self.regions, self.tracker,
            self.ffmpeg_path
        )

        self._export_worker.progress.connect(
            lambda cur, tot: progress.setValue(cur)
        )

        def on_finished(path):
            progress.close()
            self.btn_export.setEnabled(True)
            QMessageBox.information(self, "Export Complete", f"Video saved to:\n{path}")
            self.statusBar().showMessage(f"Exported: {path}")

        def on_error(msg):
            progress.close()
            self.btn_export.setEnabled(True)
            QMessageBox.critical(self, "Export Failed", msg)

        def on_cancelled():
            self._export_worker.cancel()
            self.btn_export.setEnabled(True)
            self.statusBar().showMessage("Export cancelled.")

        progress.canceled.connect(on_cancelled)
        self._export_worker.finished.connect(on_finished)
        self._export_worker.error.connect(on_error)

        self.btn_export.setEnabled(False)
        self._export_worker.start()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._stop_play()
        if self.cap:
            self.cap.release()
        event.accept()
