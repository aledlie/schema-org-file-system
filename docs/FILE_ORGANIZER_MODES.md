# File Organizer Modes

`scripts/rename_images.py` is the unified CLIP-based renamer. It selects a
vocabulary via `--profile` and an organization style via `--mode`.

## Profiles

| Profile | Vocabulary | Default mode |
|---------|-----------|--------------|
| `photo` | General photo content (sofa, dog, food, landscape...) | `in-place` |
| `screenshot` | Game-asset + software-UI categories with folder routing | `folder` |

## Modes

### `in-place`
Renames files in their original location without moving them.

- **Use case**: filename cleanup with no directory changes
- **Behavior**: `IMG_1234.jpg` → `landscape-sunset-2025-04-19.jpg` (same directory)

### `folder`
Moves and renames files into subdirectories based on detected category.

- **Use case**: organize files into category-based folder structure
- **Behavior**: `Screenshot.png` → `Software/Dashboards/dashboard-2025-04-19.png`

## Configuration

### Command-line

```bash
# Photo profile (default mode: in-place)
python scripts/rename_images.py ~/Downloads --profile photo --execute

# Screenshot profile (default mode: folder)
python scripts/rename_images.py ~/Documents/Screenshots --profile screenshot --execute

# Override mode explicitly
python scripts/rename_images.py ~/Downloads --profile photo --mode folder --execute
```

### Environment variable

```bash
export FILE_ORGANIZE_MODE=folder
python scripts/rename_images.py ~/Downloads --profile photo
```

Priority: `--mode` > `FILE_ORGANIZE_MODE` > profile default

## Implementation

`rename_images.py` defines a `RenamerProfile` dataclass holding categories,
folder mapping, refinement terms, and short names. `ImageAnalyzer` reads the
profile and runs the shared `classify_with_ocr_fallback` pipeline; results are
handed to `FileOrganizer`, which performs:

- **`in-place`**: `Path.rename()` in the original directory
- **`folder`**: `shutil.copy2()` into the resolved category subdirectory

To add a new flavor, define a `RenamerProfile` and register it in `PROFILES`.
