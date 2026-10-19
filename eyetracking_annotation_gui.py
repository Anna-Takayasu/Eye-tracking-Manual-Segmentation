#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Eye-Tracking Video Segment / Event Annotation GUI

Reusable GUI for manually marking start/end times in eye-tracking scene videos.
Existing annotations are loaded automatically and can be edited.

Default video pattern:
    <BASE_DIR>/<PARTICIPANT>/Glasses/S3/scenevideo.mp4

Example:
    python eyetracking_annotation_gui.py ^
        --base-dir "Z:\\Project\\YourProject"

Alternative folder structure:
    python eyetracking_annotation_gui.py ^
        --base-dir "D:\\StudyA" ^
        --video-pattern "eye-tracking/olympia/{participant}/scenevideo.mp4" ^
        --participants all

Dependencies:
    pip install opencv-python pandas numpy pillow
"""

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageTk


# ================================================================
# Configuration colleagues can edit
# ================================================================

# Relative path from BASE_DIR to each participant video.
# Use {participant} wherever the participant-specific folder/name appears.
# Examples:
#   {participant}/Glasses/S3/scenevideo.mp4
#   {participant}/S3/scenevideo.mp4
#   eye-tracking/olympia/{participant}/scenevideo.mp4
#   participants/{participant}/glasses/world.mp4
DEFAULT_VIDEO_PATTERN = "{participant}/Glasses/S3/scenevideo.mp4"

# Default round / condition buttons.
DEFAULT_ROUNDS = [1, 2, 3]

# Default segment / event buttons.
DEFAULT_LABELS = ["SegA", "SegB", "SegC", "SegD"]

# Human-readable names shown in the GUI. Keys are saved IDs.
LABEL_PRETTY = {
    "SegA": "SegA",
    "SegB": "SegB",
    "SegC": "SegC",
    "SegD": "SegD",
}

# By default, the predefined labels are treated as canonical.
CANONICAL_LABELS = set(DEFAULT_LABELS)


# ================================================================
# Helpers
# ================================================================

def seconds_to_hms(seconds):
    if seconds is None or not np.isfinite(float(seconds)):
        return "00:00:00.000"
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def sanitize_label(label):
    raw = str(label).strip()
    if not raw:
        return ""
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in raw)
    safe = "_".join(x for x in safe.split("_") if x)
    return safe


def participant_ids_from_range(start=1, end=16):
    return [f"P{i:02d}" for i in range(start, end + 1)]


SEGMENT_COLUMNS = [
    "participant",
    "session",
    "round",
    "segment_id",
    "segment_name",
    "segment_label",
    "segment_type",
    "analysis_compatible",
    "start_event",
    "end_event",
    "start_time_s",
    "end_time_s",
    "duration_s",
    "start_time_hms",
    "end_time_hms",
    "start_frame_idx",
    "end_frame_idx",
    "video_path",
    "valid_duration",
]


def normalize_loaded_segments(df, pid, session, video_path, fps):
    """Normalize old/new annotation CSVs to the GUI's common format."""
    if df is None or df.empty:
        return pd.DataFrame(columns=SEGMENT_COLUMNS)

    d = df.copy()

    # Derive missing IDs from older segment_name values such as R1_SegA.
    if "segment_id" not in d.columns:
        d["segment_id"] = (
            d.get("segment_name", pd.Series("", index=d.index))
            .astype(str)
            .str.extract(r"(Seg[A-Za-z0-9_-]+)", expand=False)
            .fillna("")
        )

    if "round" not in d.columns:
        d["round"] = (
            d.get("segment_name", pd.Series("", index=d.index))
            .astype(str)
            .str.extract(r"R(\d+)", expand=False)
        )

    d["round"] = pd.to_numeric(d["round"], errors="coerce").fillna(1).astype(int)

    if "segment_label" not in d.columns:
        d["segment_label"] = d["segment_id"].map(LABEL_PRETTY).fillna(d["segment_id"])

    if "segment_name" not in d.columns:
        d["segment_name"] = d.apply(
            lambda r: f"R{int(r['round'])}_{r['segment_id']}", axis=1
        )

    if "start_time_s" not in d.columns:
        d["start_time_s"] = np.nan
    if "end_time_s" not in d.columns:
        d["end_time_s"] = np.nan

    d["start_time_s"] = pd.to_numeric(d["start_time_s"], errors="coerce")
    d["end_time_s"] = pd.to_numeric(d["end_time_s"], errors="coerce")

    if "start_frame_idx" not in d.columns:
        d["start_frame_idx"] = np.round(d["start_time_s"] * fps)
    if "end_frame_idx" not in d.columns:
        d["end_frame_idx"] = np.round(d["end_time_s"] * fps)

    d["start_frame_idx"] = pd.to_numeric(d["start_frame_idx"], errors="coerce")
    d["end_frame_idx"] = pd.to_numeric(d["end_frame_idx"], errors="coerce")

    d["participant"] = pid
    d["session"] = session
    d["video_path"] = str(video_path)

    d["duration_s"] = d["end_time_s"] - d["start_time_s"]
    d["start_time_hms"] = d["start_time_s"].map(seconds_to_hms)
    d["end_time_hms"] = d["end_time_s"].map(seconds_to_hms)
    d["valid_duration"] = d["duration_s"] > 0

    d["segment_type"] = d["segment_id"].apply(
        lambda x: "canonical" if str(x) in CANONICAL_LABELS else "custom"
    )
    d["analysis_compatible"] = d["segment_id"].apply(
        lambda x: str(x) in CANONICAL_LABELS
    )

    d["start_event"] = d.apply(
        lambda r: f"R{int(r['round'])}_{r['segment_id']}_Start", axis=1
    )
    d["end_event"] = d.apply(
        lambda r: f"R{int(r['round'])}_{r['segment_id']}_End", axis=1
    )

    for c in SEGMENT_COLUMNS:
        if c not in d.columns:
            d[c] = ""

    return d[SEGMENT_COLUMNS].copy()


# ================================================================
# GUI
# ================================================================

class AnnotationGUI:
    def __init__(
        self,
        root,
        base_dir,
        video_pattern,
        participants,
        output_root,
    ):
        self.root = root
        self.base_dir = Path(base_dir)
        self.video_pattern = str(video_pattern)
        self.session = "annotation"
        self.participants = list(participants)
        self.output_root = Path(output_root)

        self.participant_index = 0
        self.pid = None
        self.video_path = None
        self.cap = None
        self.fps = 25.0
        self.frame_count = 0
        self.duration_s = 0.0
        self.current_frame = 0
        self.playing = False
        self.after_id = None

        self.current_round = tk.IntVar(value=DEFAULT_ROUNDS[0] if DEFAULT_ROUNDS else 1)
        self.current_label = tk.StringVar(value=DEFAULT_LABELS[0] if DEFAULT_LABELS else "")
        self.status_text = tk.StringVar(value="Ready")
        self.time_text = tk.StringVar(value="00:00:00.000")
        self.video_info_text = tk.StringVar(value="")

        self.labels = list(DEFAULT_LABELS)
        self.annotations = pd.DataFrame(columns=SEGMENT_COLUMNS)

        self.build_ui()
        self.load_participant(0)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------
    def build_ui(self):
        self.root.title("Eye-Tracking Video Segment / Event Annotation")
        self.root.geometry("1450x930")

        # Main split: video left, controls/table right.
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(main, width=520)
        right.pack(side="right", fill="y", padx=(10, 0))

        # ---------- Video ----------
        self.video_label = ttk.Label(left, anchor="center")
        self.video_label.pack(fill="both", expand=True)

        info = ttk.Frame(left)
        info.pack(fill="x", pady=(4, 0))

        ttk.Label(info, textvariable=self.video_info_text).pack(side="left")
        ttk.Label(
            info,
            textvariable=self.time_text,
            font=("TkDefaultFont", 12, "bold"),
        ).pack(side="right")

        # ---------- Seek bar ----------
        seek_frame = ttk.Frame(left)
        seek_frame.pack(fill="x", pady=4)

        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek = ttk.Scale(
            seek_frame,
            from_=0,
            to=1000,
            variable=self.seek_var,
            orient="horizontal",
            command=self.on_seek_drag,
        )
        self.seek.pack(fill="x", expand=True)

        # ---------- Video controls ----------
        controls = ttk.Frame(left)
        controls.pack(fill="x", pady=(3, 8))

        ttk.Button(controls, text="◀◀ 10 s", command=lambda: self.jump_seconds(-10)).pack(side="left")
        ttk.Button(controls, text="◀ 1 s", command=lambda: self.jump_seconds(-1)).pack(side="left", padx=2)
        ttk.Button(controls, text="◀ frame", command=lambda: self.jump_frames(-1)).pack(side="left", padx=2)

        self.play_button = ttk.Button(controls, text="▶ Play", command=self.toggle_play)
        self.play_button.pack(side="left", padx=8)

        ttk.Button(controls, text="frame ▶", command=lambda: self.jump_frames(1)).pack(side="left", padx=2)
        ttk.Button(controls, text="1 s ▶", command=lambda: self.jump_seconds(1)).pack(side="left", padx=2)
        ttk.Button(controls, text="10 s ▶▶", command=lambda: self.jump_seconds(10)).pack(side="left", padx=2)

        ttk.Button(
            controls,
            text="Next Video ▶",
            command=self.next_video,
        ).pack(side="right")

        # ---------- Round ----------
        round_box = ttk.LabelFrame(right, text="1. Select round / condition", padding=8)
        round_box.pack(fill="x", pady=(0, 7))

        for r in DEFAULT_ROUNDS:
            ttk.Radiobutton(
                round_box,
                text=f"R{r}",
                value=r,
                variable=self.current_round,
                command=self.on_selection_change,
            ).pack(side="left", padx=8)

        # ---------- Segment/event ----------
        self.label_box = ttk.LabelFrame(right, text="2. Select segment / event", padding=8)
        self.label_box.pack(fill="x", pady=(0, 7))

        self.label_button_frame = ttk.Frame(self.label_box)
        self.label_button_frame.pack(fill="x")

        ttk.Button(
            self.label_box,
            text="+ Add Event",
            command=self.add_custom_event,
        ).pack(fill="x", pady=(8, 0))

        self.rebuild_label_buttons()

        # ---------- Mark ----------
        mark_box = ttk.LabelFrame(right, text="3. Mark current video time", padding=8)
        mark_box.pack(fill="x", pady=(0, 7))

        self.selected_text = tk.StringVar(value="Selected")
        ttk.Label(
            mark_box,
            textvariable=self.selected_text,
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        buttons = ttk.Frame(mark_box)
        buttons.pack(fill="x")

        ttk.Button(
            buttons,
            text="MARK START",
            command=self.mark_start,
        ).pack(side="left", fill="x", expand=True, padx=(0, 3))

        ttk.Button(
            buttons,
            text="MARK END",
            command=self.mark_end,
        ).pack(side="left", fill="x", expand=True, padx=(3, 0))

        # ---------- Existing annotations ----------
        edit_box = ttk.LabelFrame(
            right,
            text="4. Existing annotations (select row to modify)",
            padding=6,
        )
        edit_box.pack(fill="both", expand=True)

        cols = ("round", "label", "start", "end", "duration")
        self.tree = ttk.Treeview(
            edit_box,
            columns=cols,
            show="headings",
            height=16,
            selectmode="browse",
        )

        self.tree.heading("round", text="Round")
        self.tree.heading("label", text="Event / Segment")
        self.tree.heading("start", text="Start")
        self.tree.heading("end", text="End")
        self.tree.heading("duration", text="Dur.")

        self.tree.column("round", width=55, anchor="center")
        self.tree.column("label", width=145)
        self.tree.column("start", width=105)
        self.tree.column("end", width=105)
        self.tree.column("duration", width=65, anchor="e")

        yscroll = ttk.Scrollbar(edit_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.jump_to_selected_start)

        edit_buttons = ttk.Frame(right)
        edit_buttons.pack(fill="x", pady=(5, 5))

        ttk.Button(
            edit_buttons,
            text="Set START = current",
            command=self.edit_selected_start,
        ).grid(row=0, column=0, sticky="ew", padx=2, pady=2)

        ttk.Button(
            edit_buttons,
            text="Set END = current",
            command=self.edit_selected_end,
        ).grid(row=0, column=1, sticky="ew", padx=2, pady=2)

        ttk.Button(
            edit_buttons,
            text="Rename",
            command=self.rename_selected,
        ).grid(row=1, column=0, sticky="ew", padx=2, pady=2)

        ttk.Button(
            edit_buttons,
            text="Delete",
            command=self.delete_selected,
        ).grid(row=1, column=1, sticky="ew", padx=2, pady=2)

        ttk.Button(
            edit_buttons,
            text="Jump to START",
            command=self.jump_to_selected_start,
        ).grid(row=2, column=0, sticky="ew", padx=2, pady=2)

        ttk.Button(
            edit_buttons,
            text="Jump to END",
            command=self.jump_to_selected_end,
        ).grid(row=2, column=1, sticky="ew", padx=2, pady=2)

        edit_buttons.columnconfigure(0, weight=1)
        edit_buttons.columnconfigure(1, weight=1)

        # ---------- Save/status ----------
        bottom = ttk.Frame(right)
        bottom.pack(fill="x")

        ttk.Button(bottom, text="Save", command=self.save_annotations).pack(side="left")
        ttk.Label(bottom, textvariable=self.status_text, wraplength=400).pack(
            side="left", padx=8
        )

    def rebuild_label_buttons(self):
        for child in self.label_button_frame.winfo_children():
            child.destroy()

        # We use radiobuttons so selection is obvious.
        for i, label in enumerate(self.labels):
            pretty = LABEL_PRETTY.get(label, label)
            rb = ttk.Radiobutton(
                self.label_button_frame,
                text=pretty,
                value=label,
                variable=self.current_label,
                command=self.on_selection_change,
            )
            rb.grid(row=i // 4, column=i % 4, sticky="ew", padx=3, pady=3)

        for c in range(4):
            self.label_button_frame.columnconfigure(c, weight=1)

    # ------------------------------------------------------------
    # Participant/video loading
    # ------------------------------------------------------------
    def annotation_paths(self):
        out_dir = self.output_root / self.pid
        out_dir.mkdir(parents=True, exist_ok=True)
        return (
            out_dir / f"{self.pid}_manual_segments.csv",
            out_dir / f"{self.pid}_manual_events.csv",
        )

    def load_participant(self, index):
        if not self.participants:
            messagebox.showerror("No participants", "No participant IDs were provided.")
            return

        index = max(0, min(index, len(self.participants) - 1))
        self.participant_index = index
        self.pid = self.participants[index]
        rel_video = self.video_pattern.format(participant=self.pid)
        self.video_path = self.base_dir / Path(rel_video)

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        if not self.video_path.exists():
            messagebox.showerror(
                "Video not found",
                f"Video not found:\n{self.video_path}"
            )
            self.status_text.set(f"Missing video for {self.pid}")
            return

        self.cap = cv2.VideoCapture(str(self.video_path))
        if not self.cap.isOpened():
            messagebox.showerror("Error", f"Could not open:\n{self.video_path}")
            return

        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(self.fps) or self.fps <= 0:
            self.fps = 25.0

        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration_s = max(0.0, (self.frame_count - 1) / self.fps)
        self.current_frame = 0
        self.playing = False
        self.play_button.configure(text="▶ Play")

        self.load_existing_annotations()
        self.refresh_table()
        self.show_frame(0)

        self.video_info_text.set(
            f"{self.pid}   "
            f"{self.video_path.name}   "
            f"{self.fps:.3f} fps   "
            f"{seconds_to_hms(self.duration_s)}"
        )
        self.status_text.set(
            f"Loaded {len(self.annotations)} existing annotation(s) for {self.pid}"
        )

    def load_existing_annotations(self):
        segments_csv, _ = self.annotation_paths()

        if segments_csv.exists():
            try:
                raw = pd.read_csv(segments_csv)
                self.annotations = normalize_loaded_segments(
                    raw, self.pid, self.session, self.video_path, self.fps
                )
            except Exception as exc:
                messagebox.showwarning(
                    "Could not load annotations",
                    f"{segments_csv}\n\n{exc}"
                )
                self.annotations = pd.DataFrame(columns=SEGMENT_COLUMNS)
        else:
            self.annotations = pd.DataFrame(columns=SEGMENT_COLUMNS)

        # Add any existing custom labels to the button list.
        self.labels = list(DEFAULT_LABELS)
        if not self.annotations.empty:
            for _, row in self.annotations.iterrows():
                label = str(row["segment_id"])
                pretty = str(row["segment_label"])
                if label and label not in self.labels:
                    self.labels.append(label)
                if pretty and pretty.lower() != "nan":
                    LABEL_PRETTY[label] = pretty

        self.rebuild_label_buttons()

    # ------------------------------------------------------------
    # Video rendering / controls
    # ------------------------------------------------------------
    def show_frame(self, frame_idx=None):
        if self.cap is None:
            return

        if frame_idx is not None:
            self.current_frame = int(np.clip(frame_idx, 0, max(0, self.frame_count - 1)))

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return

        # OpenCV BGR -> RGB.
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Fit to available display while preserving aspect ratio.
        max_w, max_h = 900, 700
        h, w = frame.shape[:2]
        scale = min(max_w / w, max_h / h, 1.0)
        if scale != 1.0:
            frame = cv2.resize(
                frame,
                (int(round(w * scale)), int(round(h * scale))),
                interpolation=cv2.INTER_AREA,
            )

        image = Image.fromarray(frame)
        photo = ImageTk.PhotoImage(image=image)
        self.video_label.configure(image=photo)
        self.video_label.image = photo

        t = self.current_time_s()
        self.time_text.set(f"{seconds_to_hms(t)}   ({t:.3f} s)")
        if self.duration_s > 0:
            self.seek_var.set(1000.0 * t / self.duration_s)

    def current_time_s(self):
        return float(self.current_frame) / float(self.fps)

    def toggle_play(self):
        if self.cap is None:
            return
        self.playing = not self.playing
        self.play_button.configure(text="⏸ Pause" if self.playing else "▶ Play")
        if self.playing:
            self.play_loop()

    def play_loop(self):
        if not self.playing:
            return

        next_frame = self.current_frame + 1
        if next_frame >= self.frame_count:
            self.playing = False
            self.play_button.configure(text="▶ Play")
            return

        self.show_frame(next_frame)
        delay_ms = max(1, int(round(1000 / self.fps)))
        self.after_id = self.root.after(delay_ms, self.play_loop)

    def jump_seconds(self, delta):
        self.playing = False
        self.play_button.configure(text="▶ Play")
        new_frame = self.current_frame + int(round(delta * self.fps))
        self.show_frame(new_frame)

    def jump_frames(self, delta):
        self.playing = False
        self.play_button.configure(text="▶ Play")
        self.show_frame(self.current_frame + int(delta))

    def on_seek_drag(self, _value):
        if self.cap is None or self.duration_s <= 0:
            return
        self.playing = False
        self.play_button.configure(text="▶ Play")
        frac = float(self.seek_var.get()) / 1000.0
        target_s = frac * self.duration_s
        self.show_frame(int(round(target_s * self.fps)))

    def next_video(self):
        self.save_annotations(silent=True)
        if self.participant_index + 1 >= len(self.participants):
            messagebox.showinfo("Finished", "This is the last participant/video.")
            return
        self.load_participant(self.participant_index + 1)

    # ------------------------------------------------------------
    # Selection / annotation creation
    # ------------------------------------------------------------
    def on_selection_change(self):
        label = self.current_label.get()
        pretty = LABEL_PRETTY.get(label, label)
        self.selected_text.set(f"Selected: R{self.current_round.get()} / {pretty}")

    def add_custom_event(self):
        raw = simpledialog.askstring(
            "Add new event",
            "Enter a new event / segment name:",
            parent=self.root,
        )
        if raw is None:
            return

        raw = raw.strip()
        if not raw:
            return

        label_id = sanitize_label(raw)
        if not label_id:
            messagebox.showerror("Invalid name", "Please enter a valid event name.")
            return

        LABEL_PRETTY[label_id] = raw
        if label_id not in self.labels:
            self.labels.append(label_id)

        self.current_label.set(label_id)
        self.rebuild_label_buttons()
        self.on_selection_change()
        self.status_text.set(f"Added event label: {raw}")

    def find_annotation_index(self, round_id, label):
        if self.annotations.empty:
            return None
        mask = (
            (pd.to_numeric(self.annotations["round"], errors="coerce") == int(round_id))
            & (self.annotations["segment_id"].astype(str) == str(label))
        )
        idxs = self.annotations.index[mask].tolist()
        return idxs[0] if idxs else None

    def ensure_annotation(self, round_id, label):
        idx = self.find_annotation_index(round_id, label)
        if idx is not None:
            return idx

        pretty = LABEL_PRETTY.get(label, label)
        row = {
            "participant": self.pid,
            "session": self.session,
            "round": int(round_id),
            "segment_id": label,
            "segment_name": f"R{int(round_id)}_{label}",
            "segment_label": pretty,
            "segment_type": "canonical" if label in CANONICAL_LABELS else "custom",
            "analysis_compatible": label in CANONICAL_LABELS,
            "start_event": f"R{int(round_id)}_{label}_Start",
            "end_event": f"R{int(round_id)}_{label}_End",
            "start_time_s": np.nan,
            "end_time_s": np.nan,
            "duration_s": np.nan,
            "start_time_hms": "",
            "end_time_hms": "",
            "start_frame_idx": np.nan,
            "end_frame_idx": np.nan,
            "video_path": str(self.video_path),
            "valid_duration": False,
        }
        self.annotations = pd.concat(
            [self.annotations, pd.DataFrame([row])],
            ignore_index=True,
        )
        return self.annotations.index[-1]

    def mark_start(self):
        r = int(self.current_round.get())
        label = self.current_label.get()
        idx = self.ensure_annotation(r, label)

        t = self.current_time_s()
        self.annotations.at[idx, "start_time_s"] = t
        self.annotations.at[idx, "start_frame_idx"] = int(self.current_frame)
        self.recalculate_row(idx)

        self.save_annotations(silent=True)
        self.refresh_table(select_index=idx)
        self.status_text.set(
            f"START set: R{r} / {LABEL_PRETTY.get(label, label)} = {seconds_to_hms(t)}"
        )

    def mark_end(self):
        r = int(self.current_round.get())
        label = self.current_label.get()
        idx = self.ensure_annotation(r, label)

        t = self.current_time_s()
        self.annotations.at[idx, "end_time_s"] = t
        self.annotations.at[idx, "end_frame_idx"] = int(self.current_frame)
        self.recalculate_row(idx)

        self.save_annotations(silent=True)
        self.refresh_table(select_index=idx)
        self.status_text.set(
            f"END set: R{r} / {LABEL_PRETTY.get(label, label)} = {seconds_to_hms(t)}"
        )

    def recalculate_row(self, idx):
        start = pd.to_numeric(
            pd.Series([self.annotations.at[idx, "start_time_s"]]),
            errors="coerce",
        ).iloc[0]
        end = pd.to_numeric(
            pd.Series([self.annotations.at[idx, "end_time_s"]]),
            errors="coerce",
        ).iloc[0]

        self.annotations.at[idx, "start_time_hms"] = (
            seconds_to_hms(start) if pd.notna(start) else ""
        )
        self.annotations.at[idx, "end_time_hms"] = (
            seconds_to_hms(end) if pd.notna(end) else ""
        )

        if pd.notna(start) and pd.notna(end):
            duration = float(end) - float(start)
            self.annotations.at[idx, "duration_s"] = duration
            self.annotations.at[idx, "valid_duration"] = duration > 0
        else:
            self.annotations.at[idx, "duration_s"] = np.nan
            self.annotations.at[idx, "valid_duration"] = False

    # ------------------------------------------------------------
    # Existing annotation table / editing
    # ------------------------------------------------------------
    def refresh_table(self, select_index=None):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if self.annotations.empty:
            return

        # Display in a stable round/start order, but preserve dataframe index as iid.
        temp = self.annotations.copy()
        temp["_idx"] = temp.index
        temp["_start_sort"] = pd.to_numeric(temp["start_time_s"], errors="coerce")
        temp = temp.sort_values(
            ["round", "_start_sort", "segment_id"],
            na_position="last",
        )

        for _, row in temp.iterrows():
            idx = int(row["_idx"])
            start = (
                seconds_to_hms(row["start_time_s"])
                if pd.notna(row["start_time_s"])
                else ""
            )
            end = (
                seconds_to_hms(row["end_time_s"])
                if pd.notna(row["end_time_s"])
                else ""
            )
            dur = (
                f"{float(row['duration_s']):.1f}s"
                if pd.notna(row["duration_s"])
                else ""
            )

            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    f"R{int(row['round'])}",
                    row["segment_label"],
                    start,
                    end,
                    dur,
                ),
            )

        if select_index is not None and str(select_index) in self.tree.get_children():
            self.tree.selection_set(str(select_index))
            self.tree.see(str(select_index))

    def selected_index(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select annotation", "Select an annotation row first.")
            return None
        return int(sel[0])

    def on_tree_select(self, _event=None):
        idx = self.selected_index_silent()
        if idx is None:
            return

        row = self.annotations.loc[idx]
        try:
            self.current_round.set(int(row["round"]))
        except Exception:
            pass

        label = str(row["segment_id"])
        if label not in self.labels:
            self.labels.append(label)
            self.rebuild_label_buttons()

        self.current_label.set(label)
        self.on_selection_change()

    def selected_index_silent(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def edit_selected_start(self):
        idx = self.selected_index()
        if idx is None:
            return
        t = self.current_time_s()
        self.annotations.at[idx, "start_time_s"] = t
        self.annotations.at[idx, "start_frame_idx"] = self.current_frame
        self.recalculate_row(idx)
        self.save_annotations(silent=True)
        self.refresh_table(select_index=idx)
        self.status_text.set(f"Updated START to {seconds_to_hms(t)}")

    def edit_selected_end(self):
        idx = self.selected_index()
        if idx is None:
            return
        t = self.current_time_s()
        self.annotations.at[idx, "end_time_s"] = t
        self.annotations.at[idx, "end_frame_idx"] = self.current_frame
        self.recalculate_row(idx)
        self.save_annotations(silent=True)
        self.refresh_table(select_index=idx)
        self.status_text.set(f"Updated END to {seconds_to_hms(t)}")

    def rename_selected(self):
        idx = self.selected_index()
        if idx is None:
            return

        current = str(self.annotations.at[idx, "segment_label"])
        raw = simpledialog.askstring(
            "Rename annotation",
            "New event / segment name:",
            initialvalue=current,
            parent=self.root,
        )
        if raw is None or not raw.strip():
            return

        raw = raw.strip()
        new_id = sanitize_label(raw)

        # Canonical labels keep their canonical ID unless the user explicitly renames
        # the ID by choosing a non-canonical name.
        old_id = str(self.annotations.at[idx, "segment_id"])
        if old_id in CANONICAL_LABELS:
            keep_id = messagebox.askyesno(
                "Keep canonical ID?",
                f"This row currently uses canonical ID '{old_id}'.\n\n"
                f"Keep the ID '{old_id}' and change only its display name?\n\n"
                "Choose 'Yes' to preserve compatibility with the paper analysis.",
            )
            if keep_id:
                new_id = old_id

        self.annotations.at[idx, "segment_id"] = new_id
        self.annotations.at[idx, "segment_label"] = raw
        self.annotations.at[idx, "segment_type"] = (
            "canonical" if new_id in CANONICAL_LABELS else "custom"
        )
        self.annotations.at[idx, "analysis_compatible"] = new_id in CANONICAL_LABELS

        r = int(self.annotations.at[idx, "round"])
        self.annotations.at[idx, "segment_name"] = f"R{r}_{new_id}"
        self.annotations.at[idx, "start_event"] = f"R{r}_{new_id}_Start"
        self.annotations.at[idx, "end_event"] = f"R{r}_{new_id}_End"

        LABEL_PRETTY[new_id] = raw
        if new_id not in self.labels:
            self.labels.append(new_id)

        self.rebuild_label_buttons()
        self.save_annotations(silent=True)
        self.refresh_table(select_index=idx)

    def delete_selected(self):
        idx = self.selected_index()
        if idx is None:
            return

        row = self.annotations.loc[idx]
        if not messagebox.askyesno(
            "Delete annotation",
            f"Delete R{int(row['round'])} / {row['segment_label']}?",
        ):
            return

        self.annotations = self.annotations.drop(index=idx).reset_index(drop=True)
        self.save_annotations(silent=True)
        self.refresh_table()
        self.status_text.set("Annotation deleted.")

    def jump_to_selected_start(self, _event=None):
        idx = self.selected_index_silent()
        if idx is None:
            return
        t = pd.to_numeric(
            pd.Series([self.annotations.at[idx, "start_time_s"]]),
            errors="coerce",
        ).iloc[0]
        if pd.notna(t):
            self.show_frame(int(round(float(t) * self.fps)))

    def jump_to_selected_end(self):
        idx = self.selected_index()
        if idx is None:
            return
        t = pd.to_numeric(
            pd.Series([self.annotations.at[idx, "end_time_s"]]),
            errors="coerce",
        ).iloc[0]
        if pd.notna(t):
            self.show_frame(int(round(float(t) * self.fps)))

    # ------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------
    def save_annotations(self, silent=False):
        if self.pid is None:
            return

        segments_csv, events_csv = self.annotation_paths()

        # One-time backup of an existing annotation file per program run.
        if segments_csv.exists() and not hasattr(self, "_backed_up"):
            self._backed_up = set()

        key = str(segments_csv)
        if segments_csv.exists() and key not in getattr(self, "_backed_up", set()):
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = segments_csv.with_name(
                segments_csv.stem + f"_backup_{stamp}" + segments_csv.suffix
            )
            try:
                shutil.copy2(segments_csv, backup)
                self._backed_up.add(key)
            except Exception:
                pass

        data = self.annotations.copy()
        if data.empty:
            data = pd.DataFrame(columns=SEGMENT_COLUMNS)

        for idx in data.index:
            self.recalculate_row(idx)

        data = data[SEGMENT_COLUMNS]
        data.to_csv(segments_csv, index=False)

        # Produce event-style START/END CSV too.
        event_rows = []
        order = 1
        for _, row in data.iterrows():
            if pd.notna(row["start_time_s"]):
                event_rows.append(
                    {
                        "participant": row["participant"],
                        "session": row["session"],
                        "event_order": order,
                        "round": row["round"],
                        "segment_id": row["segment_id"],
                        "segment_label": row["segment_label"],
                        "event_type": "start",
                        "event_name": row["start_event"],
                        "time_s": row["start_time_s"],
                        "time_hms": row["start_time_hms"],
                        "frame_idx": row["start_frame_idx"],
                        "video_path": row["video_path"],
                    }
                )
                order += 1

            if pd.notna(row["end_time_s"]):
                event_rows.append(
                    {
                        "participant": row["participant"],
                        "session": row["session"],
                        "event_order": order,
                        "round": row["round"],
                        "segment_id": row["segment_id"],
                        "segment_label": row["segment_label"],
                        "event_type": "end",
                        "event_name": row["end_event"],
                        "time_s": row["end_time_s"],
                        "time_hms": row["end_time_hms"],
                        "frame_idx": row["end_frame_idx"],
                        "video_path": row["video_path"],
                    }
                )
                order += 1

        pd.DataFrame(event_rows).to_csv(events_csv, index=False)

        if not silent:
            self.status_text.set(f"Saved: {segments_csv}")
            messagebox.showinfo("Saved", f"Annotations saved to:\n{segments_csv}")

    def on_close(self):
        try:
            self.save_annotations(silent=True)
        except Exception:
            pass

        self.playing = False
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass

        if self.cap is not None:
            self.cap.release()

        self.root.destroy()


# ================================================================
# Participant discovery
# ================================================================

def discover_participants(base_dir, video_pattern):
    """Discover participant IDs from a path pattern containing {participant}."""
    if "{participant}" not in video_pattern:
        raise ValueError(
            "Automatic participant discovery requires {participant} in --video-pattern."
        )

    glob_pattern = video_pattern.replace("{participant}", "*")
    matches = sorted(Path(base_dir).glob(glob_pattern))

    pattern_posix = video_pattern.replace("\\", "/")
    rx_text = re.escape(pattern_posix).replace(
        re.escape("{participant}"), r"(?P<participant>[^/]+)"
    )
    rx = re.compile("^" + rx_text + "$", re.I)

    found = []
    for path in matches:
        rel = path.relative_to(base_dir).as_posix()
        m = rx.match(rel)
        if m:
            found.append(m.group("participant"))

    return list(dict.fromkeys(found))


def parse_participants(values, base_dir, video_pattern):
    """Accept all, space-separated IDs, or comma-separated IDs."""
    if not values:
        return discover_participants(base_dir, video_pattern)

    flat = []
    for value in values:
        flat.extend([x.strip() for x in str(value).split(",") if x.strip()])

    if len(flat) == 1 and flat[0].lower() == "all":
        return discover_participants(base_dir, video_pattern)

    return flat


# ================================================================
# CLI
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description="GUI manual segment/event annotation for eye-tracking videos."
    )

    parser.add_argument(
        "--base-dir",
        required=True,
        help="Project/data root directory.",
    )

    parser.add_argument(
        "--video-pattern",
        default=DEFAULT_VIDEO_PATTERN,
        help=(
            "Relative video path containing {participant}. "
            f'Default: "{DEFAULT_VIDEO_PATTERN}"'
        ),
    )

    parser.add_argument(
        "--participants",
        nargs="*",
        default=["all"],
        help=(
            "Participant IDs: P01 P02 P03, P01,P02,P03, or all. "
            "Default: all participants discovered from --video-pattern."
        ),
    )

    parser.add_argument(
        "--output-dir",
        default=None,
        help="Default: <BASE_DIR>/manual_segment_annotations",
    )

    args = parser.parse_args()
    base_dir = Path(args.base_dir)

    if not base_dir.exists():
        raise FileNotFoundError(f"Base directory does not exist: {base_dir}")

    participants = parse_participants(
        args.participants, base_dir, args.video_pattern
    )

    if not participants:
        raise FileNotFoundError(
            "No participant videos found.\n"
            f"Base directory: {base_dir}\n"
            f"Video pattern: {args.video_pattern}\n"
            "Check the path pattern or pass participant IDs explicitly."
        )

    output_root = (
        Path(args.output_dir)
        if args.output_dir
        else base_dir / "manual_segment_annotations"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    print("Eye-tracking annotation GUI")
    print("=" * 70)
    print(f"Base directory : {base_dir}")
    print(f"Video pattern  : {args.video_pattern}")
    print(f"Participants   : {', '.join(participants)}")
    print(f"Output         : {output_root}")
    print("=" * 70)

    root = tk.Tk()
    AnnotationGUI(
        root=root,
        base_dir=base_dir,
        video_pattern=args.video_pattern,
        participants=participants,
        output_root=output_root,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
