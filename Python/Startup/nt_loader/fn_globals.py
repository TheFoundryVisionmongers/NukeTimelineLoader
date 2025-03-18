"""
Module that contains globals used throughout the NT loader system.
Note: ntl_main.py contains SCHEMA_MAP a schema mapping dictionaries to drive QT treeviews which is referenced in the
BASE_OPTIONS["Shotgrid View"]
"""

import os

# ---
# __INTEGRATE__ Globals for Connection to Shotgrid/Flow
# ---
# setup global for studio SG/Flow site
SHOTGUN_URL = "https://your.studio.shotgrid"
# retrieve the current status icons from shotgrid
STATUS_PNG_URL = f"{SHOTGUN_URL}/images/sg_icon_image_map.png"
# Below can vary depending on studio structure. If the default is blocked follow below instructions
STATUS_CSS_URL = f"{SHOTGUN_URL}/dist/production/stylesheets/base.css"
# To find the appropriate css file navigate to any table page that shows statuses in shotgrid . using your browser go into
# developer mode and look at the sources tab to find the required base css file see nt_loader/Python/sg_css_for_hiero_tags.PNG
# if your studio self hosts SG it may be look similar to below
# STATUS_CSS_URL = f"{SHOTGUN_URL}/stylesheets/minified/base_#UUID#.css"

# ---
# __CUSTOMIZE__ SG Note publish settings
# ---
# Alter below template should you want a different subject applied to published notes
SG_NOTE_SUBJECT_TEMPLATE = "Hiero Review Note - "

# ---
# __CUSTOMIZE__ Shotgrid Globals to denote what entity fields the required data is
# ---
# This may need alteration depending on how your studio uses shotgrid
SG_ENCODED_MEDIA_FIELDS = "sg_uploaded_movie"
SG_IMAGE_SEQUENCE_FIELDS = "sg_path_to_frames"
SG_MOVIE_FIELDS = "sg_path_to_movie"
SG_MOVIE_PATH_FIELDS = "sg_path_to_movie"

# Optional - To help in debugging/optimization below sets the fields in which data should be collected from SG entities.
# Provide a dictionary of the Entity and required fields to optimize manifest synchronization.
# If a process calling an entity is not defined in the dictionary it will default to "All" and be visible in the
# sg_manifest.json to aid debug
# setting to "All" will collect the entity in its entirety which can be useful when designing what data is required to
# be passed to Hiero.
# SG_ENTITY_FIELD_SYNC = "All"
SG_ENTITY_FIELD_SYNC = {
    "Playlist": [
        "id",
        "type",
        "code",
        "version",
        "versions",
        "notes",
        "open_notes",
        "attachments",
        "updated_at",
    ],
    "Cut": [
        "id",
        "type",
        "version",
        "cached_display_name",
        "notes",
        "open_notes",
        "sg_status_list",
        "attachments",
        "cut_items",
        "updated_at",
    ],
    "CutItem": [
        "id",
        "type",
        "version",
        "cached_display_name",
        "cut_order",
        "cut_item_in",
        "cut_item_out",
        "edit_in",
        "edit_out",
        "timecode_start_text",
        "updated_at",
    ],
    "Version": [
        "id",
        "type",
        "code",
        "sg_status_list",
        "updated_at",
        SG_ENCODED_MEDIA_FIELDS,
        SG_IMAGE_SEQUENCE_FIELDS,
        SG_MOVIE_FIELDS,
        SG_MOVIE_PATH_FIELDS,
        "notes",
        "open_notes",
        "project",
    ],
    "Note": [
        "id",
        "type",
        "project",
        "content",
        "replies",
        "created_by",
        "created_at",
        "updated_at",
        "sg_status_list",
        "attachments",
        "addressings_to",
        "subject",
    ],
    "Reply": [
        "id",
        "type",
        "content",
        "user",
        "created_at",
        "updated_at",
        "sg_status_list",
    ],
}

# Optional - Add API key string below if using API key connection. Note: enabling this approach will override above
# authentication globals. WARNING you will need to customize this codebase as it is built with the tk-core web login
# with authenticating users permission restrictions in mind.
SHOTGUN_API_KEY = None

# ---
# __CUSTOMIZE__ Mixed OS path mapping
# ---
# Optional - uncomment and alter with the subsequent dictionary for path substitutions should you be running a mixed OS
# environment and only have 1 path to media in  SG fields pointing to paths
# SG_ENCODED_MEDIA_FIELDS, SG_IMAGE_SEQUENCE_FIELDS, SG_MOVIE_FIELDS,SG_MOVIE_PATH_FIELDS
# See fn_helpers.py:convert_media_path_to_map. This converts just before import to hiero bin in
# fn_hiero_func:hiero_add_files_to_bin.
# The index of the list value is used for substitution.
# SG_MEDIA_PATH_MAP = {"Windows":["v:", "z:"],
#                      "Linux": ["/mnt/media/v", "/mnt/media/z"],
#                      "Darwin": ["/media/v", "/media/z"] # OSX
#                      }
SG_MEDIA_PATH_MAP = {}

# ---
# __CUSTOMIZE__ Globals to set correct localization directory
# ---
# To avoid repeated "choose localization directory" dialogs un comment below with desired path
# os.environ["SG_LOCALIZE_DIR"] = ""
# Desired path can be driven by environment variable
DEFAULT_LOCALIZE_DIR = os.environ.get("SG_LOCALIZE_DIR", None)
# Mostly used internally to assess if the project requires Shotgrid/Flow tags to be created
SG_TAGS_CREATED = os.environ.get("SG_TAGS_CREATED", False)

# ---
# __CUSTOMIZE__ Globals for options and options tabs
# ---
# Show or hide the options tab to the users
OPTIONS_VISIBLE = True
# option json file to override OPTIONS_BASE save json file with dictionary similar to below example
CUSTOM_OPTIONS_FILE = None
#CUSTOM_OPTIONS_FILE = "path/to/options/file.json"
# Options file can have disabled options starting with # in the key
# and default options marked with * in the value.
# Bools are defaulted to their initial state
OPTIONS_BASE = {
    "Shotgrid View": [
        "Playlist and Cuts*",
        "Shot and Sequence",
    ],  # Required to drive QT Treeview
    "Attached cut file import strategy": [
        "Used SG Cuts*",
        "Import EDL and relink",
        "Import OTIO and relink",
    ],
    "Import to loaded sequence": False,
    "Import SG annotations to timeline": False,
    "Custom import configuration": False,
    "Show only open notes": False,
    "Show only notes addressed to me": False,
    "#Copy/Download threadcount": ["Full*", "Half", "Quarter"],
    "Cut lead in frames": ["1000*"],
}


# Based ntl_main.py schemas which entities do not have right click context capabilities in the UI.
# IE: You would never want a user to localize an entire Project !
NON_CONTEXT_ENTITIES = ["Project", "Task"]


# ---
# __CUSTOMIZE__ Globals for context actions
# ---
# Default actions for right click. To customize functionality view nt_loader.fn_ui.ShotGridLoaderWidget.action_stub
CONTEXT_ACTIONS = [
    "Localize SG encoded media/s",
    # Removing below as this is a double up in features - Hiero has a localization of directly linked files into fast
    # cache ready formatting however studios may want this feature to copy to a machine for review
    # "Localize image sequences/s",
    # "Localize movie media/s",
    "Direct link to image sequences/s",
    "Direct link to movie media/s",
    "---",
    "Sync SG notes",
    "---",
    "Clear Edits",
    "Clear SG Manifests",
    "Change Localize Directory",
]
