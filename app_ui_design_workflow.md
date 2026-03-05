# PySide6 + Qt Designer Lab Workflow

## Architecture

form.ui (XML, Claude reads/edits) → pyside6-uic → ui_form.py (auto-generated)
app.py (Python, you own; Claude adds callbacks/logic)


## Converting an Existing App

**Step 1:** Ask Claude to analyze app.py and output widget inventory
**Step 2:** Recreate the UI in Qt Designer (drag-drop, ~30-45 min)
**Step 3:** Run: pyside6-uic form.ui -o ui_form.py
**Step 4:** Ask Claude to refactor app.py to use the generated UI (all callbacks stay)

## Adding Features

**You ask:** "Add a new button to form.ui and a callback in app.py to handle it"

*Claude:
Edits form.ui (XML)
Adds callback to app.py
Tells you: "Run: pyside6-uic form.ui -o ui_form.py"

**You:** Run the command, test, done.

## Key Rule
ui_form.py is auto-generated (always fresh, never edit)
app.py callbacks are safe (loosely coupled through widget names)
form.ui is the source of truth for UI structure

## Files in Git
Commit: form.ui, app.py
Don
*