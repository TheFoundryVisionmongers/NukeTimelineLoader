#!/usr/bin/env python

import os
import os.path
import shutil
import sys
import stat


def build(source_path, build_path, install_path, targets):
    print("Building: ", targets," >> ", source_path, " @ ", build_path, " >>> ", install_path, "\n")

    def _build():
        
        src_py = ""
        try:
            # python source
            src_py = os.path.join(source_path, "python")
            dest_py = os.path.join(build_path, "python")

            if not os.path.exists(dest_py):
                shutil.copytree(src_py, dest_py)
        except Exception as e:
            print("Exception - Skipping : {} - \n{}".format(src_py, e))
        
        src_bin = ""
        try:
            # binaries
            mode = (stat.S_IRUSR | stat.S_IRGRP |
                    stat.S_IXUSR | stat.S_IXGRP)

            src_bin = os.path.join(source_path, "bin")
            dest_bin = os.path.join(build_path, "bin")

            if not os.path.exists(dest_bin):
                shutil.copytree(src_bin, dest_bin)

                for name in os.listdir(dest_bin):
                    filepath = os.path.join(dest_bin, name)
                    os.chmod(filepath, mode)
        except Exception as e:
            print("Exception - Skipping : {} - \n{}".format(src_bin, e))

    def _install():
        for name in ("bin", "python"):
            try:
                src = os.path.join(build_path, name)
                dest = os.path.join(install_path, name)

                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
            except Exception as e:
                print("Exception - Skipping : {} - \n{}".format(src, e))

    _build()

    if "install" in (targets or []):
        _install()


if __name__ == '__main__':
    build(
        source_path=os.environ['REZ_BUILD_SOURCE_PATH'],
        build_path=os.environ['REZ_BUILD_PATH'],
        install_path=os.environ['REZ_BUILD_INSTALL_PATH'],
        targets=sys.argv[1:]
    )