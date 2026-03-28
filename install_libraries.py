import os
import sys
import subprocess
import platform

def run_command(command):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + command)
    except subprocess.CalledProcessError as e:
        print(f"Error installing dependencies: {e}")
        return False
    return True

def main():
    print("=== LED Hack Tools - Dependency Installer ===")
    print(f"Operating System: {platform.system()} {platform.release()}")
    print(f"Python Version: {sys.version.split()[0]}")
    print("-" * 45)

    dependencies = ["psutil", "pygame"]
    
    # 1. Standard Pip dependencies
    print(f"Installing Python packages: {', '.join(dependencies)}...")
    if run_command(dependencies):
        print("[✓] Successfully installed Python dependencies.")
    else:
        print("[!] Failed to install some Python dependencies via pip.")

    # 2. OS Specific Instructions (Tkinter)
    print("\nChecking for Tkinter (GUI support)...")
    try:
        import tkinter
        print("[✓] Tkinter is already installed and working.")
    except ImportError:
        print("[!] Tkinter not found.")
        if platform.system() == "Windows":
            print("    -> ACTION: Please modify your Python installation and check 'tcl/tk and IDLE'.")
        elif platform.system() == "Darwin": # Mac
            print("    -> ACTION: Run this command in your terminal:")
            print("       brew install python-tk")
        else: # Linux
            print("    -> ACTION: Run this command in your terminal:")
            print("       sudo apt-get install python3-tk")

    print("-" * 45)
    print("Done. You can now run the LED tools.")
    input("Press Enter to exit...")

if __name__ == "__main__":
    main()
