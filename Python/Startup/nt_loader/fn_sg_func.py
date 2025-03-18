import os
import queue
import re
import getpass

import requests
from io import BytesIO
from PIL import Image
import urllib

from nt_loader.fn_globals import (
    SHOTGUN_URL,
    SHOTGUN_API_KEY,
    SG_ENTITY_FIELD_SYNC,
    STATUS_PNG_URL,
    STATUS_CSS_URL
)
from tank_vendor.shotgun_api3 import Shotgun
from tank_vendor.shotgun_api3.lib import sgtimezone
from tank.authentication import login_dialog, constants, errors
from tank.authentication import session_cache

# Used to interact with Shotgrid/Flow REST functionality
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}

class SGWrapper(Shotgun):
    def __init__(self, *args, **kwargs):
        """
        Class override to correctly pass required information from
        session_token. This enables alternate approach to retrieve SG calls
        """
        self._session_id = kwargs["sg_session_id"]
        del kwargs["sg_session_id"]
        super(SGWrapper, self).__init__(*args, **kwargs)

    def _call_rpc(self, *args, **kwargs):
        self.config.session_token = self._session_id
        return super(SGWrapper, self)._call_rpc(*args, **kwargs)


class WebLoginDialog(login_dialog.LoginDialog):
    """
    A wrapper class for LoginDialog that strictly enforces web-based authentication.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the dialog, forcing web login method.
        """
        # Override any environment variables that could affect login method
        import os

        os.environ.pop("SGTK_FORCE_STANDARD_LOGIN_DIALOG", None)
        os.environ.pop("SGTK_DEFAULT_AUTH_METHOD", None)

        super(WebLoginDialog, self).__init__(*args, **kwargs)

        # Force web login method and hide options
        self.method_selected = constants.METHOD_WEB_LOGIN
        self.ui.button_options.setVisible(False)

    def _authenticate(self, error_label, site, login, password, auth_code=None):
        """
        Override to only allow web-based authentication.
        """
        if not self._sso_saml2:
            raise errors.AuthenticationError(
                "Web login is required but not available. Please ensure your Qt installation supports web authentication."
            )

        profile_location = login_dialog.LocalFileStorageManager.get_site_root(
            site, login_dialog.LocalFileStorageManager.CACHE
        )

        res = self._sso_saml2.login_attempt(
            host=site,
            http_proxy=self._http_proxy,
            cookies=self._session_metadata,
            product=login_dialog.PRODUCT_IDENTIFIER,
            profile_location=profile_location,
        )

        if res == login_dialog.QtGui.QDialog.Accepted:
            self._new_session_token = self._sso_saml2.session_id
            self._session_metadata = self._sso_saml2.cookies
            self.accept()
        else:
            error_msg = self._sso_saml2.session_error
            if error_msg:
                raise errors.AuthenticationError(error_msg)

    def _toggle_web(self, method_selected=None):
        """
        Override to prevent switching away from web login.
        """
        return

    def _update_ui_according_to_site_support(self):
        """
        Override to skip site checks and force web UI configuration.
        """
        # Configure UI for web login without checking site capabilities
        self.ui.site.setFocus(login_dialog.QtCore.Qt.OtherFocusReason)
        self.ui.login.setVisible(False)
        self.ui.password.setVisible(False)


def instance_handler():
    """Handles authentication and SG class instantiation prompting for Auth if session timed out

    Returns:
        session, sg (object, object): wrapped shotgrid api object for use in direct Qt calls
    """
    # Handle API key authentication if defined
    if SHOTGUN_API_KEY:
        sg = SGWrapper(
            SHOTGUN_URL,
            script_name="api_user",
            api_key=SHOTGUN_API_KEY,
            sg_session_id=None,
            session_token=None,
        )

        return sg  # Return None for session since we're using API key

    user = session_cache.get_current_user(SHOTGUN_URL)
    try:
        session_data = session_cache.get_session_data(SHOTGUN_URL, user)
        sg = SGWrapper(
            SHOTGUN_URL,
            sg_session_id=session_data["session_token"],
            session_token=session_data["session_token"],
        )
        return sg

    except Exception as e:
        if not SHOTGUN_API_KEY:
            print("Session Expired initializing SG login dialog")

            login_window = WebLoginDialog(True, hostname=SHOTGUN_URL)
            # Result of successful login
            session = login_window.result()
            user = session[1]
            session_cache.cache_session_data(SHOTGUN_URL, user, session[2])
            session_cache.set_current_user(SHOTGUN_URL, user)
            sg = SGWrapper(
                SHOTGUN_URL, sg_session_id=session[2], session_token=session[2]
            )
            return sg
        else:
            raise Exception("Failed to authenticate with API key")


def session_handler():
    """Handles authentication and SG class instantiation prompting for Auth if session timed out

    Returns:
        session, sg (object, object): wrapped shotgrid api object for use in direct Qt calls
    """
    # Handle API key authentication if defined
    if SHOTGUN_API_KEY:
        sg = SGWrapper(
            SHOTGUN_URL,
            script_name="api_user",
            api_key=SHOTGUN_API_KEY,
            sg_session_id=None,
            session_token=None,
        )
        # Test connection
        test = sg.find("Status", [], ["id"])
        return None, sg  # Return None for session since we're using API key

    user = session_cache.get_current_user(SHOTGUN_URL)
    try:
        session_data = session_cache.get_session_data(SHOTGUN_URL, user)
        sg = SGWrapper(
            SHOTGUN_URL,
            sg_session_id=session_data["session_token"],
            session_token=session_data["session_token"],
        )
        test = sg.find("Status", [], ["id"])
        return session_data["session_token"], sg

    except Exception as e:
        if not SHOTGUN_API_KEY:
            print("Session Expired initializing SG login dialog")

            login_window = WebLoginDialog(True, hostname=SHOTGUN_URL)
            # Result of successful login
            session = login_window.result()
            user = session[1]
            session_cache.cache_session_data(SHOTGUN_URL, user, session[2])
            session_cache.set_current_user(SHOTGUN_URL, user)
            sg = SGWrapper(
                SHOTGUN_URL, sg_session_id=session[2], session_token=session[2]
            )
            return session[2], sg
        else:
            raise Exception("Failed to authenticate with API key")

def get_session_user():
    """

    Returns:

    """
    return session_cache.get_current_user(SHOTGUN_URL)

# Shotgrid is not threadsafe so this creates a pool to be used by threading
class SgInstancePool:
    """Pool of SHotgrid API sessions required as SG api is not threadsafe"""

    def __init__(self, maxsize):
        self.pool = queue.Queue(maxsize)
        self.maxsize = maxsize
        for _ in range(maxsize):
            sg_instance = instance_handler()
            self.pool.put(sg_instance)

    def get_sg_instance(self):
        return self.pool.get()

    def release_sg_instance(self, sg_instance):
        self.pool.put(sg_instance)

    def is_finished(self):
        if self.pool.full():
            return True
        else:
            return False


def access_token(session_token):
    """Retrieve an access token from a session token

    Args:
        session_token (str): encoded string from sg session data see

    Raises:
        Exception: error if session is expired or incorrect

    Returns:
        str: access token valid for 3 minutes
    """
    auth_payload = urllib.parse.urlencode(
        {"session_token": session_token, "grant_type": "session_token"}
    )
    response = requests.post(
        f"{SHOTGUN_URL}/api/v1.1/auth/access_token",
        headers=HEADERS,
        data=auth_payload,
        verify=False,
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        raise Exception("Failed to retrieve Auth token")


def get_rest_data(access_token, entity, sg, id=None, fields=True):
    """Rest based SG query

    Args:
        access_token (str): encoded access token derived from session see
                            access_token()
        entity (str): Name of SG entity to query
        id (int, optional): specific sg id to query. Defaults to None.
        fields (bool, optional): when True return all applicable fields.
                                Defaults to True.

    Raises:
        Exception: Fails to find applicable data will raise

    Returns:
        dict: dict of json response data relating to query
    """
    HEADERS["Authorization"] = f"Bearer {access_token}"

    if not fields:
        params = {}
    else:
        params = {"fields": ",".join(list(sg.schema_field_read(entity))) + ",url"}
    url_path = f"{SHOTGUN_URL}/api/v1.1/entity/{entity}"
    if id:
        url_path = f"{SHOTGUN_URL}/api/v1.1/entity/{entity}/{id}"
    response = requests.get(url_path, headers=HEADERS, params=params, verify=False)
    if response.status_code == 200:
        return response.json()["data"]
    else:
        raise Exception(f"Failed to retrieve data")


# ---
# SG status Icon functions
# ---


def fetch_css(url):
    """Use Shotgrid site CSS to later parse required icons for tags.
    NOTE: base.css can be located at differing places based on the studio.
    when in doubt browse to any page that has statuses and inspect in a browser
    navigate to sources tab and look for .css sometimes the file can be called base_#UUID.css
    change this in fn_globals

    Args:
        url (str): Url to collect css from

    Raises:
        Exception: html errors

    Returns:
        response (str): contents of response.text. in this case a css file
    """
    response = requests.get(url)
    if response.status_code == 200:
        return response.text
    else:
        raise Exception(f"Failed to fetch CSS. Status code: {response.status_code}")


def extract_css_info(css, png_url, sg_statuses):
    """Parse collected CSS file for icon information. SG uses a single png to drive all icons this will
    cut this png into usable icons

    Args:
        css (str): retrieved css content as str
        png_url (str): url to the shotgrid icons png
        sg_statuses (list): list of str for the required statuses to collect

    Returns:
        icons_info (str):
    """
    png_file = re.findall(r"\/images\/(.*).*?", png_url)[-1]
    pattern = r"div.*?_(\w+).*?width:\s*(\d+)px.*height:\s*(\d+)px.*?.*?-(\d*).*?-(\d*)"
    matches = re.finditer(pattern, css)
    icons_info = []
    for match in matches:
        if png_file in match.group(0):
            for stat in sg_statuses:
                if stat["relationships"]["icon"]["data"]["name"] in match.group(0):
                    icons_info.append(
                        {
                            "icon_name": stat["attributes"]["code"],
                            "width": int(match.group(2)),
                            "height": int(match.group(3)),
                            "x_offset": int(match.group(4)),
                            "y_offset": int(match.group(5)),
                        }
                    )
                if stat["attributes"]["code"] == match.group(1):
                    icons_info.append(
                        {
                            "icon_name": stat["attributes"]["code"],
                            "width": int(match.group(2)),
                            "height": int(match.group(3)),
                            "x_offset": int(match.group(4)),
                            "y_offset": int(match.group(5)),
                        }
                    )
    return icons_info


def create_icons(png_url, css_url, localize_dir, sg_statuses):
    """Output a usable icon png from SG icons. for use in hiero tags and reports

    Args:
        png_url (str): Url path to sg icons
        css_url (str): Url to collect css from
        localize_dir (str): root directory to create status_tags and save icon files
        sg_statuses (list): list of str for the required statuses to collect

    Returns:
        icon_data (list): list of dicts containing icon data for use in NT loader
    """
    icon_data = []
    try:
        # Fetch and process CSS
        css = fetch_css(css_url)
        icons_info = extract_css_info(css, png_url, sg_statuses)
        if not icons_info:
            print("Failed to extract information from CSS.")
            return

        # Fetch SG PNG image
        response = requests.get(png_url)
        if response.status_code != 200:
            print(f"Failed to fetch PNG. Status code: {response.status_code}")
            return
        tags_path = os.path.join(localize_dir, "status_tags")
        # Create output directory if it doesn't exist
        os.makedirs(tags_path, exist_ok=True)

        # Open the image from the response content
        with Image.open(BytesIO(response.content)) as source_img:
            for icon_info in icons_info:
                # Calculate the region to crop
                left = icon_info["x_offset"]
                top = icon_info["y_offset"]
                right = left + icon_info["width"]
                bottom = top + icon_info["height"]
                # Crop the image
                icon = source_img.crop((left, top, right, bottom))

                # Resize to 32x32
                icon = icon.resize((32, 32), Image.LANCZOS)

                # Save the icon
                output_path = os.path.join(
                    tags_path, f"icon_{icon_info['icon_name']}.png"
                )
                icon.save(output_path)
                # some icons have dual use for the sake of simplicity I duplicate these
                if "fin" in os.path.basename(output_path):
                    repeat_icon = {
                        "name": "vwd",
                        "icon_path": os.path.join(tags_path, f"icon_vwd.png"),
                    }
                    icon.save(repeat_icon["icon_path"])
                    icon_data.append(repeat_icon)
                    repeat_icon = {
                        "name": "clsd",
                        "icon_path": os.path.join(tags_path, f"icon_clsd.png"),
                    }
                    icon.save(repeat_icon["icon_path"])
                    icon_data.append(repeat_icon)
                # some icons have dual use for the sake of simplicity I duplicate these -
                if "rdy" in os.path.basename(output_path):
                    repeat_icon = {
                        "name": "opn",
                        "icon_path": os.path.join(tags_path, f"icon_opn.png"),
                    }
                    icon.save(repeat_icon["icon_path"])
                    icon_data.append(repeat_icon)

                icon_data.append(
                    {"name": icon_info["icon_name"], "icon_path": output_path}
                )

    except Exception as e:
        print(f"An error occurred: {e}")

    return icon_data


def setup_sg_tags(sg, session_token, localize_path):
    """Retrieve tags from shotgrid and place the in a workable location

    Args:
        sg (object): SGwrapper instantiated class
        session_token (str): SG session token
        localize_path (str): root path to create directory for icons and tags

    Returns:
        (list): of dict pertaining to the currently setup tags for later use in Foundry manifest Base entity
    """
    token = access_token(session_token)
    sg_statuses = get_rest_data(token, "Status", sg, fields=True)
    tag_data = create_icons(STATUS_PNG_URL, STATUS_CSS_URL, localize_path, sg_statuses)
    tag_data = {tuple(sorted(d.items())): d for d in tag_data}
    for icon in list(tag_data.values()):
        for stat in sg_statuses:
            if icon["name"] == stat["attributes"]["code"]:
                icon["lname"] = stat["attributes"]["cached_display_name"]

    return list(tag_data.values())


# ---
# Tree Model Parent/Child data functions __CUSTOMIZE__
# ---


# Functions to fetch data for parent TreeItem node type using ShotGrid API
def sg_tree_get_projects(parent_item, sg_instance):
    """Collect SG data for projects

    Args:
        parent_item (QObject): parent model item
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (dict): Formated for display in tree model

    """
    projects = sg_instance.find(
        "Project", [["sg_status", "is", "Active"]], ["id", "name", "sg_status_list"]
    )
    return [
        {
            "name": project["name"],
            "node_type": "Project",
            "item_status": project.get("sg_status_list"),
            "data": project,
        }
        for project in projects
    ]


def sg_tree_get_playlists(project_item, sg_instance):
    """Collect SG data for playlists

    Args:
        project_item (QObject): parent model item
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (dict): Formated for display in tree model

    """
    project = project_item.data
    playlists = sg_instance.find(
        "Playlist",
        [["project", "is", project]],
        ["id", "code", "sg_status_list", "updated_at"],
    )
    if not playlists:
        return [
            {
                "name": "No Playlist Data",
                "node_type": "No Data",
            }
        ]

    return [
        {
            "name": playlist["code"],
            "node_type": "Playlist",
            "item_status": playlist.get("sg_status_list"),
            "data": playlist,
        }
        for playlist in playlists
    ]


def sg_tree_get_cuts(project_item, sg_instance):
    """Collect SG data for cuts

    Args:
        project_item (QObject): parent model item
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (dict): Formated for display in tree model

    """
    project = project_item.data
    cuts = sg_instance.find(
        "Cut",
        [["project", "is", project]],
        ["id", "cached_display_name", "sg_status_list", "updated_at"],
    )
    if not cuts:
        return [
            {
                "name": "No Cut Data",
                "node_type": "No Data",
            }
        ]

    return [
        {
            "name": cut["cached_display_name"],
            "node_type": "Cut",
            "item_status": cut.get("sg_status_list"),
            "data": cut,
        }
        for cut in cuts
    ]


def sg_tree_get_sequences(project_item, sg_instance):
    """Collect SG data for sequences

    Args:
        project_item (QObject): parent model item
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (dict): Formated for display in tree model

    """
    project = project_item.data
    sequences = sg_instance.find(
        "Sequence",
        [["project", "is", project]],
        ["id", "code", "sg_status_list", "updated_at"],
    )

    if not sequences:
        return [
            {
                "name": "No Sequence Data",
                "node_type": "No Data",
            }
        ]

    return [
        {
            "name": sequence["code"],
            "node_type": "Sequence",
            "item_status": sequence.get("sg_status_list"),
            "data": sequence,
        }
        for sequence in sequences
    ]


def sg_tree_get_shots(sequence_item, sg_instance):
    """Collect SG data for shots

    Args:
        sequence_item (QObject): parent model item
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (dict): Formated for display in tree model
    """
    sequence = sequence_item.data
    shots = sg_instance.find(
        "Shot",
        [["sg_sequence", "is", sequence]],
        ["id", "code", "sg_status_list", "updated_at"],
    )

    if not shots:
        return [
            {
                "name": "No Shot Data",
                "node_type": "No Data",
            }
        ]

    return [
        {
            "name": shot["code"],
            "node_type": "Shot",
            "item_status": shot.get("sg_status_list"),
            "data": shot,
        }
        for shot in shots
    ]


def sg_tree_get_tasks(shot_item, sg_instance):
    """Collect SG data for tasks

    Args:
        shot_item (QObject): parent model item
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (dict): Formated for display in tree model

    """
    shot = shot_item.data
    tasks = sg_instance.find(
        "Task", [["entity", "is", shot]], ["id", "content", "sg_status_list"]
    )

    if not tasks:
        return [
            {
                "name": "No Shot Data",
                "node_type": "No Data",
            }
        ]

    return [
        {
            "name": task["content"],
            "node_type": "Task",
            "item_status": task.get("sg_status_list"),
            "data": task,
        }
        for task in tasks
    ]


def sg_tree_get_versions(entity_item, sg_instance):
    """Collect SG data for versions

    Args:
        entity_item (QObject): parent model item
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (dict): Formated for display in tree model
    """
    entity = entity_item.data
    entity_type = entity_item.node_type

    if entity_type == "Playlist":
        versions = sg_instance.find(
            "Version",
            [["playlists", "in", [entity]]],
            ["id", "code", "sg_status_list", "updated_at"],
        )

    if entity_type == "Cut":
        cutitems = sg_instance.find(
            "CutItem", [["cut", "is", entity]], ["id", "code", "version"]
        )
        if cutitems:
            versions = sg_instance.find(
                "Version",
                [
                    [
                        "id",
                        "in",
                        [
                            x["version"]["id"]
                            for x in cutitems
                            if "offline_" not in x["code"]
                        ],
                    ]
                ],
                ["id", "code", "sg_status_list", "updated_at"],
            )

    if entity_type == "Task":
        versions = sg_instance.find(
            "Version",
            [["sg_task", "is", entity]],
            ["id", "code", "sg_status_list", "updated_at"],
        )

    if entity_type == "Shot":
        versions = sg_instance.find(
            "Version",
            [["entity", "is", entity]],
            ["id", "code", "sg_status_list", "updated_at"],
        )

    if not versions:
        return [
            {
                "name": "No {} Version Data".format(entity_type),
                "node_type": "No Data",
            }
        ]

    return [
        {
            "name": version["code"],
            "node_type": "Version",
            "item_status": version.get("sg_status_list"),
            "data": version,
        }
        for version in versions
    ]


def sg_tree_get_assets(project_item, sg_instance):
    """UNUSED . __CUSTOMIZE__ Example of assets incase schema needs asset in studio

    Args:
        project_item (QObject): project item from Qtree
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (list): formatted list of assets names for UI display

    """
    project = project_item.data
    assets = sg_instance.find(
        "Asset", [["project", "is", project]], ["id", "code", "sg_status_list"]
    )
    return [
        {
            "name": asset["code"],
            "node_type": "Asset",
            "item_status": asset.get("sg_status_list"),
            "data": asset,
        }
        for asset in assets
    ]


# tree_panel search bar Search function
def sg_tree_search_entities(_, sg_instance, project_name, entity_type, search_term):
    """Search bar call to retrieve filtered content for model schema

    Args:
        _ (Qobject): Unused parent object
        sg_instance (object): SG instance from SgInstancePool
        project_name (str): Project name from Project combo
        entity_type (str): Entity type from Entity combo
        search_term (str): Search term from QlineEdit

    Returns:

    """
    project = sg_instance.find_one("Project", [["name", "is", project_name]], [])
    search_name = "code"
    if entity_type == "Cut":
        search_name = "cached_display_name"
    filters = [["project", "is", project], [search_name, "contains", search_term]]
    entities = sg_instance.find(
        entity_type, filters, ["id", search_name, "sg_status_list", "updated_at"]
    )

    if not entities:
        return [
            {
                "name": "No {} Search Data".format(entity_type),
                "node_type": "No Data",
            }
        ]

    return [
        {
            "name": entity[search_name],
            "node_type": entity_type,
            "item_status": entity.get("sg_status_list"),
            "data": entity,
        }
        for entity in entities
    ]


# ---
# SG entity collection functions
# ---


def sg_get_playlist_sort_order(sg_instance, playlist_id):
    """Collect SG data for playlist sort order

    Args:
        sg_instance (object): SG instance from SgInstancePool
        playlist_id (int): sg playlist id

    Returns:
        (dict): for use in manifests to assemble correct order of playlist version on import

    """
    return sg_instance.find(
        "PlaylistVersionConnection",
        [["playlist", "is", {"type": "Playlist", "id": playlist_id}]],
        list(sg_instance.schema_field_read("PlaylistVersionConnection").keys()),
    )


def sg_get_valid_statuses(sg_instance, entity):
    """Collect SG data for valid statuses for use in UIs

    Args:
        sg_instance (object): SG instance from SgInstancePool
        entity (dict): SG entity object

    Returns:
        (dict): formatted for use in fn manifest base entity

    """
    statuses_info = sg_instance.schema_field_read(entity, "sg_status_list")
    return statuses_info["sg_status_list"]["properties"]["valid_values"]["value"]


def sg_get_req_entity_details(sg_instance, entity, entity_ids, get_all=False):
    """Generic collect required details from entity. This is filtered for optimized performance using
    globals.py:SG_ENTITY_FIELD_SYNC

    Args:
        sg_instance (object): SG instance from SgInstancePool
        entity (str): SG entity string
        entity_ids (list): list of entity ids
        get_all (bool): get all entity details

    Returns:
        (dict): entity dictionary for use in SG manifest

    """
    fields = SG_ENTITY_FIELD_SYNC.get(entity, None)
    if not fields:
        fields = list(sg_instance.schema_field_read(entity).keys())
    if get_all:
        fields = list(sg_instance.schema_field_read(entity).keys())
    return sg_instance.find(
        entity,
        [["id", "in", entity_ids]],
        fields,
    )


def sg_get_projects_for_combobox(_, sg_instance):
    """Seperate function to retrieve projects to drive combo box . Is seperated to provide better UI feel
    Args:
        _ (Qobject): Unused parent object
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (list): list of project names from Project combobox
    """
    projects = sg_instance.find("Project", [["sg_status", "is", "Active"]], ["name"])
    return [{"name": project["name"]} for project in projects]


def sg_get_version_thumb_filmstrip(parent_item, sg_instance, manifest_crud):
    """Get sg thumbnails and filmstrips to save and display in UI

    Args:
        parent_item (QObject): parent item from Qtree
        sg_instance (object): SG instance from SgInstancePool
        manifest_crud (Qobject): Manifest CRUD object

    Returns:
        (list) : paths and duration of version content to drive filemscrubber widget

    """
    manifest_directory = manifest_crud.get_database_directory()
    thumb_directory = os.path.join(manifest_directory, "filmstrips")
    os.makedirs(thumb_directory, exist_ok=True)
    version = sg_get_req_entity_details(
        sg_instance, "Version", parent_item.data["id"], get_all=True
    )[-1]
    thumb_response = requests.get(version.get("image"))
    filmstrip_response = requests.get(version.get("filmstrip_image"))
    with Image.open(BytesIO(thumb_response.content)) as thumb_img:
        thumb_file = os.path.join(
            thumb_directory, "ThumbnailVersion-{}.jpg".format(version["id"])
        )
        thumb_img.save(thumb_file)
    try:
        # Found that different version of SG create alternate image formats if image is not recognized except
        with Image.open(BytesIO(filmstrip_response.content)) as filmstrip_img:
            duration = "_".join(str(version.get("uploaded_movie_duration")).split("."))
            filmstrip_file = os.path.join(
                thumb_directory,
                "FilmSTripVersion-{}-{}.jpg".format(version["id"], duration),
            )
            filmstrip_img.save(filmstrip_file)
    except:
        # save out binary file
        duration = "_".join(str(version.get("uploaded_movie_duration")).split("."))
        filmstrip_file = os.path.join(
            thumb_directory,
            "FilmSTripVersion-{}-{}.jpg".format(version["id"], duration),
        )
        attachment = {"url": version.get("filmstrip_image")}
        sg_instance.download_attachment(attachment, filmstrip_file)

    data_list = [thumb_file, filmstrip_file, version["uploaded_movie_duration"]]
    if len(data_list) < 3:
        data_list = [thumb_file, "", 0]

    return data_list


def sg_get_attachments(sg_instance, attachment_ids):
    """Collect SG Attachment entity information

    Args:
        sg_instance (object): SG instance from SgInstancePool
        attachment_ids (list): list of attachment ids

    Returns:
        (list): list of attachments

    """
    return sg_instance.find(
        "Attachment",
        [["id", "in", attachment_ids]],
        list(sg_instance.schema_field_read("Attachment").keys()),
    )


def sg_download_annotations(sg_instance, attachment_ids, localize_path):
    """

    Args:
        sg_instance:
        attachment_ids:
        localize_path:

    Returns:

    """
    attachment_path = os.path.join(localize_path, "attachments")
    os.makedirs(attachment_path, exist_ok=True)
    annotations = []
    attachment_entities = sg_get_attachments(sg_instance, attachment_ids)
    for attachment in attachment_entities:
        if "annot" in attachment["this_file"]["name"]:
            try:
                # Annotations in studio do not always follow below SG pattern
                # Rename to avoid hiero interpreting sg name as a file sequence
                altered_filename = "{}_{}Frame.{}".format(
                    attachment["this_file"]["name"].split(".")[0],
                    attachment["this_file"]["name"].split(".")[1],
                    attachment["this_file"]["name"].split(".")[2],
                )
            except IndexError:
                # If the above pattern is not used embed the attachment id at the start
                altered_filename = "{}_{}".format(
                    attachment["id"], attachment["this_file"]["name"]
                )

            filename = os.path.join(attachment_path, altered_filename)
            if not os.path.isfile(filename):
                annotations.append(
                    {
                        "id": attachment["id"],
                        "created": attachment["created_at"],
                        "localize_path": filename,
                    }
                )
                sg_instance.download_attachment(attachment, filename)

    return annotations


# ---
# SG alteration functions
# ---


def sg_add_note(
    sg_instance,
    fn_sg_manifest_entity,
    fn_change_entity,
):
    """

    Args:
        sg_instance:
        fn_sg_manifest_entity:
        fn_change_entity:

    Returns:

    """
    status = "opn"
    # __CUSTOMIZE__ Optional if using SHOTGUN_API_KEY logic to define the active user will need to be applied
    if SHOTGUN_API_KEY:
        raise Exception("ERROR submitting user not defined while using SHOTGUN_API_KEY. Search # __CUSTOMIZE__ Optional if using SHOTGUN_API_KEY ")
    session_user = session_cache.get_current_user(SHOTGUN_URL) or getpass.getuser()
    user = sg_instance.find_one(
        "HumanUser",
        [["email", "contains", session_user]],
        list(sg_instance.schema_field_read("HumanUser").keys()),
    )


    project_id = fn_sg_manifest_entity["project"]["id"]
    link_entity = {
        "id": fn_sg_manifest_entity["id"],
        "name": fn_sg_manifest_entity["code"],
        "type": fn_sg_manifest_entity["type"],
    }

    data = {
        "project": {"type": "Project", "id": project_id},
        "subject": fn_change_entity["subject"],
        "content": fn_change_entity["comment"]["comment"],
        "sg_status_list": status,
    }

    data["note_links"] = [link_entity]

    data["user"] = {"type": "HumanUser", "id": user["id"], "name": user["name"]}

    note = sg_instance.create("Note", data)

    if fn_change_entity.get("images", None):
        for image in fn_change_entity["comment"]["images"]:
            sg_instance.upload("Note", note["id"], image, field_name="attachments")

    return note


def sg_add_reply(
    sg_instance,
    fn_change_entity,
):
    """

    Args:
        sg_instance:
        fn_change_entity:

    Returns:

    """
    session_user = session_cache.get_current_user(SHOTGUN_URL) or getpass.getuser()
    user = sg_instance.find_one(
        "HumanUser",
        [["email", "contains", session_user]],
        list(sg_instance.schema_field_read("HumanUser").keys()),
    )
    data = {
        "content": fn_change_entity["comment"]["comment"],
        "entity": {"type": "Note", "id": fn_change_entity["sg_note_id"]},
    }

    data["user"] = {"type": "HumanUser", "id": user["id"], "name": user["name"]}
    reply = sg_instance.create("Reply", data)

    if fn_change_entity.get("images", None):
        for image in fn_change_entity["comment"]["images"]:
            sg_instance.upload(
                "Note", fn_change_entity["sg_note_id"], image, field_name="attachments"
            )

    return reply


def sg_update_status(sg_instance, fn_sg_manifest_entity, status):
    data = {}
    data["sg_status_list"] = status

    sg_instance.update(fn_sg_manifest_entity["type"], fn_sg_manifest_entity["id"], data)

    return sg_instance.find_one(
        fn_sg_manifest_entity["type"],
        [["id", "is", fn_sg_manifest_entity["id"]]],
        list(sg_instance.schema_field_read(fn_sg_manifest_entity["type"]).keys()),
    )
