import os
import sys

import hiero
import nt_loader.fn_sg_func
from nt_loader.fn_ui import LoadingDialog, ShotgridLoaderWidget
from qtpy.QtCore import QTimer

# Default schema mapping node types to their child-fetching functions
# This approach is to provide a customizable QT treeview that can be
# simply adapted to differing structures and fields used in production
# databases. This can be adapted to structures other than Shotgrid/Flow
DEFAULT_SCHEMA = {
    "root": {"Project": nt_loader.fn_sg_func.sg_tree_get_projects},
    "Project": {
        "Playlist": nt_loader.fn_sg_func.sg_tree_get_playlists,
        "Cut": nt_loader.fn_sg_func.sg_tree_get_cuts,
    },
    "Playlist": {
        "Version": nt_loader.fn_sg_func.sg_tree_get_versions
    },  # Last child is Version
    "Cut": {"Version": nt_loader.fn_sg_func.sg_tree_get_versions},
    # 'Version' nodes have no children
}

# __CUSTOMIZE__ Alternate Schema which needs downstream handling customized by studio
# in nt_loader.fn_sg_func there is also an example of assets
SEQUENCE_SHOT = {
    "root": {"Project": nt_loader.fn_sg_func.sg_tree_get_projects},
    "Project": {
        "Sequence": nt_loader.fn_sg_func.sg_tree_get_sequences,
    },
    "Sequence": {"Shot": nt_loader.fn_sg_func.sg_tree_get_shots},
    "Shot": {"Task": nt_loader.fn_sg_func.sg_tree_get_tasks},
    "Task": {
        "Version": nt_loader.fn_sg_func.sg_tree_get_versions,
        "_searchable": False,
    },  # Last child is Version
    # 'Version' nodes have no children
}
# Schemas mapped by fn_globals.py OPTIONS_BASE
SCHEMA_MAP = {"Playlist and Cuts": DEFAULT_SCHEMA, "Shot and Sequence": SEQUENCE_SHOT}


def after_project_load(event):
    """This sets up NT loader for the new project by hooking into the callback
    "kAfterNewProjectCreated"

    Args:
        event (object): Hiero callback event object . Unused in this function
    """
    loading_dialog = LoadingDialog("Initializing\nNuke Timeline Loader")
    loading_dialog.show()

    def on_load():
        session_token, sg = nt_loader.fn_sg_func.session_handler()
        widget = ShotgridLoaderWidget(sg, session_token, SCHEMA_MAP)
        # widget.show()
        wm = hiero.ui.windowManager()
        wm.addWindow(widget)
        loading_dialog.close()

    QTimer.singleShot(3000, on_load)


# Register the NTL after_project_load function to be triggered on hiero callback
hiero.core.events.registerInterest("kAfterNewProjectCreated", after_project_load)
