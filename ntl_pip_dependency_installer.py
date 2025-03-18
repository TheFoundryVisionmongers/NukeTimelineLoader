import os
import subprocess
import sys
import site

# This is a boilerplate specific to windows for studios with less package management infrastructure
# IE: Rez, Pipenv etc.
# to run :
# - Alter path to correct location for nuke site packages see below
# - Open cmd terminal as administrator
# - run : "C:\Program Files\Nuke15.1v1\python.exe" ntl_pip_dependency_installer_windows.py


# __INTEGRATE__ Set the alternate site-packages location
alternate_location = "C:/Program Files/Nuke15.1v1/pythonextensions/site-packages"

# Ensure the alternate location exists
os.makedirs(alternate_location, exist_ok=True)

# Add the alternate location to sys.path
sys.path.insert(0, alternate_location)

# Add the alternate location to site.PREFIXES
site.PREFIXES.insert(0, alternate_location)

# Packages to install
packages = [
    "requests",
    "urllib3",
    "pillow",
    "qtpy",
    "fileseq",
    "opencv-python",
    "numpy==1.26.4",
    "git+https://github.com/shotgunsoftware/tk-core.git@v0.21.7",
]

# Install packages
for package in packages:
    print(f"Installing {package}...")
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            f"--target={alternate_location}",
            package,
        ]
    )

print(f"Packages installed successfully in {alternate_location}")
