name = "hiero"
version = "15.0.4"

# build command can be extended to include cmake etc - this currently just copies required code and bin across to rez_package location
build_command = "rez env python -- python {root}/build.py {install}"

requires = []

tools = []


@early()
def tools():
    import os

    return [x for x in os.listdir("bin")]


# __INTEGRATE__ change below environment to suite studio infrastructure
_env = {
    "HIERO_EXECUTABLE": "C:/Program Files/Nuke15.1v1/Nuke15.1.exe",
    "HIERO_VERSION": version,
    "HIERO_HOME": "C:/Program Files/Nuke15.0v4",
    "foundry_LICENSE": "4101@localhost",
    "PATH": [],
    "PYTHON_PATH": [],
    "PYTHONDONTWRITEBYTECODE": 1,
}

# __INTEGRATE__ update if studio is using linux
_linux = {
    "HIERO_EXECUTABLE": "",
    "HIERO_VERSION": version,
    "HIERO_HOME": "",
    "foundry_LICENSE": "",
    "PATH": [],
    "LD_LIBRARY_PATH": [],
}


def commands():
    import platform

    global env
    global this
    global system
    global expandvars

    _environment = this._env
    if platform.system().lower() == "linux":
        _environment.update(this._linux)

    for key, value in _environment.items():
        if isinstance(value, (tuple, list)):
            [env[key].append(expandvars(v)) for v in value]
        else:
            env[key] = expandvars(value)

    env.PATH.prepend("{}".format(_environment["HIERO_HOME"]))
    env.PATH.append("{root}/bin")
