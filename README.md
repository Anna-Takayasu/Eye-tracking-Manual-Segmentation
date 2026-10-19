# Eye-Tracking Manual Segment / Event Annotation

A small Python GUI for manually annotating **start and end times of segments/events** in eye-tracking scene videos.

## Features

- Play / pause video
- Move backward/forward by 1 s or 10 s
- Frame-by-frame navigation
- Seek bar
- Next participant/video
- Default round/condition buttons
- Default segment/event buttons
- Add custom event labels during annotation
- Load and edit existing annotations
- Change previously marked START / END times
- Rename or delete annotations
- Export segment and event CSV files

## Installation

Python 3.9+ is recommended.

```bash
pip install -r requirements.txt
```

## Default folder structure

The default video pattern is:

```text
<BASE_DIR>/<PARTICIPANT>/Glasses/S3/scenevideo.mp4
```

Example:

```text
Z:\Project\YourProject\
├── P01\Glasses\S3\scenevideo.mp4
├── P02\Glasses\S3\scenevideo.mp4
└── P03\Glasses\S3\scenevideo.mp4
```

Run all detected participants:

```bat
python eyetracking_annotation_gui.py ^
  --base-dir "Z:\Project\YourProject"
```

`all` is the default. You can also write it explicitly:

```bat
python eyetracking_annotation_gui.py ^
  --base-dir "Z:\Project\YourProject" ^
  --participants all
```

Run selected participants:

```bat
python eyetracking_annotation_gui.py ^
  --base-dir "Z:\Project\YourProject" ^
  --participants P01 P02 P03
```

or:

```bat
python eyetracking_annotation_gui.py ^
  --base-dir "Z:\Project\YourProject" ^
  --participants P01,P02,P03
```

Participant names do not have to be `P01`, `P02`, etc. They may be `11`, `12`, `Subject01`, `VP003`, and so on.

## Different folder structure

Use `--video-pattern`. Put `{participant}` where the participant-specific folder/name occurs.

Example:

```text
D:\StudyA\eye-tracking\olympia\11\scenevideo.mp4
D:\StudyA\eye-tracking\olympia\12\scenevideo.mp4
```

Run:

```bat
python eyetracking_annotation_gui.py ^
  --base-dir "D:\StudyA" ^
  --video-pattern "eye-tracking/olympia/{participant}/scenevideo.mp4" ^
  --participants all
```

Another example:

```text
<BASE_DIR>/participants/<PARTICIPANT>/glasses/world.mp4
```

Use:

```bat
--video-pattern "participants/{participant}/glasses/world.mp4"
```

## Change the default round / condition buttons

Edit near the top of `eyetracking_annotation_gui.py`:

```python
DEFAULT_ROUNDS = [1, 2, 3]
```

For example:

```python
DEFAULT_ROUNDS = [1, 2]
```

or:

```python
DEFAULT_ROUNDS = [1, 2, 3, 4]
```

## Change the default segment / event buttons

Edit:

```python
DEFAULT_LABELS = ["SegA", "SegB", "SegC", "SegD"]
```

For another project:

```python
DEFAULT_LABELS = [
    "Intersection",
    "SharedPath",
    "MixedTraffic",
    "Conflict",
]
```

Optional display names are set in:

```python
LABEL_PRETTY = {
    "SegA": "Shared path",
    "SegB": "Residential street",
    "SegC": "Arterial road",
    "SegD": "Mixed traffic",
}
```

The dictionary key is the saved ID; the value is the text shown in the GUI.

You can also click **+ Add Event** during annotation, so every event does not need to be defined in advance.

## Existing annotations

Existing annotation CSV files are loaded automatically.

Select a row and use:

- **Set START = current**
- **Set END = current**
- **Rename**
- **Delete**
- **Jump to START**
- **Jump to END**

## Output

Default output:

```text
<BASE_DIR>/manual_segment_annotations/<PARTICIPANT>/
```

Example:

```text
manual_segment_annotations/
└── P01/
    ├── P01_manual_segments.csv
    └── P01_manual_events.csv
```

Choose another output location with:

```bat
--output-dir "D:\StudyA\annotations"
```


## Windows note

To change drives/folders in Command Prompt:

```bat
cd /d "Z:\Project\YourProject"
```
