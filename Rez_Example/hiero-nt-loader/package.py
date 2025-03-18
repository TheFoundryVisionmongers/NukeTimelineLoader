name = "hiero_nt_loader"
version = "0.1.0"

# build command can be extended to include cmake etc - this currently just copies required code and bin across to rez_package location
build_command = "rez env python -- python {root}/build.py {install}"

requires = [
    "requests",
    "urllib3",
    "pillow",
    "qtpy",
    "tank",
    "sgtk",
    "opencv-python",
    "numpy",
]
# __INTEGRATE__ Rez package requirements
# The tank and sgtk requirements are available inside tk-core
# using pip install "git+https://github.com/shotgunsoftware/tk-core.git@v0.21.7" with get these.
# requirements depending on how your studio handles pip and rez this may need some alteration.
# qtpy is a QT shim that recognizes PySide2 which is embedded in nuke https://pypi.org/project/QtPy/


def commands():
    env.NUKE_PATH = "{root}/python"
    env.PYTHONPATH.append("{root}/python")
