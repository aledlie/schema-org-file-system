# File Organizer Modes

Both `image_content_renamer.py` and `screenshot_renamer.py` now use the `FileOrganizer` class with support for two organization modes.

## Modes

### `in-place` mode
Renames files in their original location without moving them to subdirectories.

- **Use case**: Simple filename cleanup while keeping files in original directories
- **Default for**: `image_content_renamer.py`
- **Behavior**: `IMAGE.jpg` → `landscape-sunset-2025-04-19.jpg` (same directory)

### `folder` mode
Moves and renames files to subdirectories based on detected content category.

- **Use case**: Organize files into category-based folder structure
- **Default for**: `screenshot_renamer.py`
- **Behavior**: `screenshot.png` → `Software/Dashboards/dashboard-2025-04-19.png`

## Configuration

### Command-line argument

```bash
# image_content_renamer.py
python scripts/image_content_renamer.py --source ~/Downloads --mode folder

# screenshot_renamer.py
python scripts/screenshot_renamer.py ~/Documents/Screenshots --mode in-place -x
```

### Environment variable

```bash
# Set default mode globally
export FILE_ORGANIZE_MODE=folder

# Then scripts use it as fallback
python scripts/image_content_renamer.py --source ~/Downloads
```

Priority: CLI argument > Environment variable > Script default

## Implementation Details

Both scripts now:
1. Create an analyzer (ImageAnalyzer or ScreenshotAnalyzer)
2. Pass it to FileOrganizer with the desired mode
3. FileOrganizer handles the actual organization:
   - **in-place mode**: Uses `Path.rename()` to rename in original location
   - **folder mode**: Uses `shutil.copy2()` to move to subdirectories

The FileOrganizer class abstracts the organization logic, making it reusable for any image analysis task.
