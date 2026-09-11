"""
Entry point used by PyInstaller to build IDS_DEA_Logger.exe

Run on Windows:
    build_exe.bat
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client.main_app import main

if __name__ == "__main__":
    main()
