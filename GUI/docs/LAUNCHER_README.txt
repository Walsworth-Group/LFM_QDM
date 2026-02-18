============================================================
          GUI Application Launcher Instructions
============================================================

You now have TWO convenient ways to launch the GUI apps:

1. "Launch GUI Apps.bat" (in main project folder)
   - Shows a console window with status messages
   - Good for debugging and seeing if there are errors
   - The console stays open if something goes wrong
   - Recommended for first-time use

2. "Launch GUI Apps (Silent).vbs" (in main project folder)
   - NO console window - cleaner experience
   - GUI apps appear directly
   - Recommended once everything is working

============================================================
                    How to Use
============================================================

METHOD 1 - Double-click the file:
   Simply double-click either launcher file and the GUI
   apps will start automatically!

METHOD 2 - Create a desktop shortcut:
   1. Right-click on "Launch GUI Apps.bat"
   2. Select "Send to" > "Desktop (create shortcut)"
   3. Now you can launch from your desktop!

METHOD 3 - Pin to taskbar (Windows 10/11):
   1. Right-click the .bat file
   2. Select "Pin to taskbar"
   3. Click the taskbar icon to launch

============================================================
              Custom Python Environment
============================================================

If you're using a conda environment or virtual environment,
you need to edit the .bat file:

1. Open "Launch GUI Apps.bat" in a text editor
2. Find the section marked "Option 2" or "Option 3"
3. Uncomment (remove "REM") and modify for your setup
4. Comment out (add "REM") the default "python" line

Example for conda:
   REM python launch_all_apps.py
   call conda activate odmr_env
   python launch_all_apps.py

============================================================
                   Troubleshooting
============================================================

Problem: "python is not recognized as a command"
Solution: Make sure Python is installed and added to PATH,
          or edit the .bat file to use the full Python path

Problem: Script crashes immediately
Solution: Use the .bat file (not .vbs) to see error messages

Problem: Wrong Python version
Solution: Edit the .bat file to specify the full path to
          your Python executable (see Option 4)

============================================================
