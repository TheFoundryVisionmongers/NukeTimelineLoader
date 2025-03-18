import os
import datetime
from pathlib import Path
import fileseq


from nt_loader.fn_sg_func import (
    sgtimezone,
    sg_get_req_entity_details,
    sg_get_playlist_sort_order,
    sg_download_annotations,
)
from nt_loader.fn_helpers import filter_versions_ids, get_sorted_values
from nt_loader.fn_workers import UPDATE_SIGNALS


###
# manifest_functions
###


def create_fn_localization_strategy_entities(
    manifest_crud, entity_ids, localize_key, override=False, direct=False
):
    """Function to create a Foundry manifest entity which details the localization strategy approach for the version.
    This is used down stream to import into hiero bin and timeline. This entity is not considered localized until
    complete_fn_localization_strategy_entities

    EXAMPLE:
        {
        "id": 100,
        "localized": false,
        "to_refresh": false,
        "fn_type": "LocalizeStrategy",
        "created_at": "2024-09-26 16:47:57.032044-07:00",
        "sg_version_id": 710,
        "download_file_path": "C:/modular2\\versions\\BBB_08_a-team_019_COMP_001.mov",
        "sg_url": "https://sg-media-usor-01.s3-accelerate.amazonaws.com/truncated...",
        "localize_type": "Download",
        "updated_at": "2024-09-26 16:47:57.643986-07:00"
        }

    Args:
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
        entity_ids (list): of int SG manifest version ids to create entities for
        localize_key (str): key used to unpack required field in SG version entity IE: sg_version["path_to_images"]
        override (bool): Used for mixed approach localization strategies. IE: download some content but direct link to
        other content
        direct (bool): when used in conjunction with a localize_key which has path to attached storage check if the file
        is accessible and link

    Returns:
        (list) : Foundry manifest ID created for later use by fn_workers.ImageSequenceCopier, fn_workers.SGDownloader or
        direct linked in fn_hiero_func.hiero_add_files_to_bin and fn_hiero_func.hiero_add_playlist_or_cut_to_timeline

    """
    localize_directory = manifest_crud.get_database_directory()
    manifest_crud.select_database("FOUNDRY")
    fn_version_link_entities = manifest_crud.read(filters=[("sg_id", "in", entity_ids)])
    version_ids = []
    for vl in fn_version_link_entities:
        version_ids.extend(vl.get("sg_version_ids"))
    manifest_crud.select_database("SG")
    sg_manifest_version_entities = manifest_crud.read(
        filters=[("id", "in", version_ids)]
    )
    localize_path = os.path.join(localize_directory, "versions")
    os.makedirs(localize_path, exist_ok=True)
    download_paths = []
    copy_paths = []
    direct_paths = []
    for_localize_list = []

    if "uploaded" in localize_key:
        for sg_version in sg_manifest_version_entities:
            version_file = os.path.join(localize_path, sg_version[localize_key]["name"])
            if not os.path.exists(version_file):
                download_paths.append(version_file)
                for_localize_list.append(
                    {
                        "sg_version_id": sg_version["id"],
                        "download_file_path": version_file,
                        "sg_url": sg_version[localize_key]["url"],
                        "localize_type": "Download",
                    }
                )
            # if override:
            #     download_paths.append(version_file)
            #     for_localize_list.append(
            #         {
            #             "sg_version_id": sg_version["id"],
            #             "download_file_path": version_file,
            #             "sg_url": sg_version[localize_key]["url"],
            #             "localize_type": "Download",
            #         }
            #     )

    if "_path_to_" in localize_key:
        for sg_version in sg_manifest_version_entities:
            if not sg_version[localize_key]:
                UPDATE_SIGNALS.details_text.emit(
                    True,
                    'No SG "{}" for Version: {}'.format(
                        localize_key, sg_version["code"]
                    ),
                )
                continue

            source_path = Path(sg_version[localize_key])
            if not os.path.exists(source_path):
                # double check if the source_path is actually an image sequence
                if fileseq.findSequenceOnDisk(source_path):
                    pass
                else:
                    UPDATE_SIGNALS.details_text.emit(
                        True,
                        "Unreachable Source Path {} for Version: {}".format(
                            source_path, sg_version["code"]
                        ),
                    )
                    continue

            if not direct:
                version_file = os.path.join(
                    localize_path, os.path.basename(source_path)
                )
                if not os.path.exists(version_file):
                    copy_paths.append(version_file)
                    for_localize_list.append(
                        {
                            "sg_version_id": sg_version["id"],
                            "copy_file_path": version_file,
                            "sg_source": str(source_path),
                            "localize_type": "Copy",
                        }
                    )
                # if override:
                #     copy_paths.append(version_file)
                #     for_localize_list.append(
                #         {
                #             "sg_version_id": sg_version["id"],
                #             "copy_file_path": version_file,
                #             "sg_source": str(source_path),
                #             "localize_type": "Copy",
                #         }
                #     )
            else:
                version_file = source_path
                UPDATE_SIGNALS.details_text.emit(
                    False, "Direct Linking - {}".format(version_file)
                )
                direct_paths.append(version_file)
                for_localize_list.append(
                    {
                        "sg_version_id": sg_version["id"],
                        "direct_file_path": str(source_path),
                        "localize_type": "Direct",
                    }
                )

    if download_paths:
        for_localize_list = [
            x
            for x in for_localize_list
            if x["download_file_path"] in list(set(download_paths))
        ]

    if copy_paths:
        for_localize_list = [
            x
            for x in for_localize_list
            if x["copy_file_path"] in list(set([str(x) for x in copy_paths]))
        ]

    if direct_paths:
        for_localize_list = [
            x
            for x in for_localize_list
            if x["direct_file_path"] in list(set([str(x) for x in direct_paths]))
        ]

    manifest_crud.select_database("FOUNDRY")
    fn_localized_strategy_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "LocalizeStrategy")]
    )
    id_list = []
    for localize in for_localize_list:
        [
            manifest_crud.delete(x["id"])
            for x in fn_localized_strategy_entities
            if x["sg_version_id"] == localize["sg_version_id"]
        ]
        fn_localize_entity = {
            "id": "__UNIQUE__",
            "localized": False,
            "to_refresh": False,
            "fn_type": "LocalizeStrategy",
            "created_at": datetime.datetime.now(sgtimezone.LocalTimezone()),
        }
        fn_localize_entity.update(localize)
        new_entity = manifest_crud.create(fn_localize_entity)
        id_list.append(new_entity["id"])

    return id_list


def complete_fn_localization_strategy_entities(manifest_crud, fn_localized_ids):
    """Update existing Foundry manifest localization strategy entities as files are copied, downloaded or linked

    Args:
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui
        fn_localized_ids (list): list of int Foundry manifest ids to update

    """
    manifest_crud.select_database("FOUNDRY")
    fn_localized_strategy_entities = manifest_crud.read(
        filters=[("id", "in", fn_localized_ids), ("fn_type", "eq", "LocalizeStrategy")]
    )
    for entity in fn_localized_strategy_entities:
        localized_entity = entity
        localized_entity.update(
            {
                "localized": True,
                "updated_at": datetime.datetime.now(sgtimezone.LocalTimezone()),
            }
        )
        manifest_crud.update(entity["id"], localized_entity)


def create_fn_version_link_entities(manifest_crud, sg_entity_ids):
    """Create a summarized Foundry manifest entity which contains the parent import type and the subsequent related
    versions. This is collected from SG manifest

    EXAMPLE:
        {
        "id": 102,
        "sg_id": 10,
        "fn_type": "VersionLink",
        "sg_type": "Playlist",
        "sg_name": "Team Dailies",
        "sg_version_ids": [
          6729,
          6728,
          6727,
          6726,
          6725,
          6724,
          6723,
          6722,
          6721,
          6720,
          6719
        ],
        "created_at": "2024-09-27 09:23:03.542563-07:00"
        }

    Args:
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
        sg_entity_ids (list): list of int SG manifest ids to summarize

    Returns:
        (list) : Foundry manifest ID created for later use by fn_workers.ImageSequenceCopier, fn_workers.SGDownloader or
        direct linked in fn_hiero_func.hiero_add_files_to_bin and fn_hiero_func.hiero_add_playlist_or_cut_to_timeline
    """
    manifest_crud.select_database("SG")
    sg_manifest_entities = manifest_crud.read(filters=[("id", "in", sg_entity_ids)])
    fn_ids = []
    manifest_crud.select_database("FOUNDRY")
    fn_version_link_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "VersionLink")]
    )

    for sg_entity in sg_manifest_entities:
        cut_item_ids = [x["id"] for x in sg_entity.get("cut_items", [])]
        version_ids = [x["id"] for x in sg_entity.get("versions", [])]

        if sg_entity["type"] == "Version":
            version_ids = [sg_entity["id"]]
            sg_name = sg_entity["code"]

        if sg_entity["type"] == "Playlist":
            try:
                # studio may not have sg_sort_order set fail if so
                versions = get_sorted_values(
                    sg_entity["sg_sort_order"], value_key="version"
                )
            except TypeError:
                # fallback to PlaylistVersionConnection list order
                versions = [x["version"] for x in sg_entity["sg_sort_order"]]
            version_ids = [x["id"] for x in versions]
            sg_name = sg_entity["code"]
        if cut_item_ids:
            cut_version_ids = [x["version"]["id"] for x in sg_entity.get("cut_items")]
            version_ids.extend(cut_version_ids)
            sg_name = sg_entity["cached_display_name"]
        [
            manifest_crud.delete(x["id"])
            for x in fn_version_link_entities
            if x["sg_id"] == sg_entity["id"]
        ]

        # Custom offline handling if offline available fn_version_link_entity["sg_version_ids"][-1] is offline
        offline_version_id = ""
        if sg_entity["type"] == "Cut":
            # path_to_offline = sg_entity["cut.Cut.version.Version.sg_path_to_movie"]
            offline_version = sg_entity.get("version")
            if offline_version:
                offline_version_id = offline_version.get("id")
                version_ids.append(offline_version_id)

        # __CUSTOMIZE__ add studio specific VersionLink entity handling for sequences, shot, latest etc
        fn_version_link_entity = {
            "id": "__UNIQUE__",
            "sg_id": sg_entity["id"],
            "fn_type": "VersionLink",
            "sg_type": sg_entity["type"],
            "sg_name": sg_name,
            "sg_version_ids": version_ids,
            "created_at": datetime.datetime.now(sgtimezone.LocalTimezone()),
        }
        manifest_crud.select_database("FOUNDRY")
        fn_entity = manifest_crud.create(fn_version_link_entity)
        fn_ids.append(fn_entity["id"])
    return fn_ids


def create_fn_import_tasks_entity(manifest_crud, fn_entity_ids):
    """
    Creates an internal report of required bin import and sequence import tasks. Is updated to with completion/failure
    states to ensure smooth operation of UI regardless of failure states. Used additionally to avoid excess computation
    for imports im current session.

    Args:
        manifest_crud: (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
        fn_entity_ids: (list): list of int FN manifest ids to summarize

    Returns:
        (int) id of the import tasks entity

    """
    manifest_crud.select_database("FOUNDRY")
    fn_import_tasks_entity = {
        "id": "__UNIQUE__",
        "fn_type": "ImportTasks",
        "fn_ids_import": fn_entity_ids,
        "completion_tally": [],
        "failure_tally": [],
        "stage": "bin_import",  # bin_import or timeline_import
        "state": "new",  # new, ip, comp or fail.
        "created_at": datetime.datetime.now(sgtimezone.LocalTimezone()),
    }
    new_entity = manifest_crud.create(fn_import_tasks_entity)
    return new_entity["id"]


def update_fn_import_tasks_entity(manifest_crud, fn_import_tasks_id, data):
    """
    updates an existing import tasks entity
    Args:
        manifest_crud:
        fn_import_task_id:
        data:

    Returns:

    """
    manifest_crud.select_database("FOUNDRY")
    fn_import_tasks_entity = manifest_crud.read(
        filters=[("id", "in", [fn_import_tasks_id]), ("fn_type", "eq", "ImportTasks")]
    )
    if fn_import_tasks_entity:
        fn_import_tasks_entity[-1].update(data)
        manifest_crud.update(fn_import_tasks_id, fn_import_tasks_entity[-1])


def check_fn_import_tasks_allowed(manifest_crud):
    """
    Checks the state of all oll fn ImportTask entities to ensure they are completed before allowing additional imports
    Args:
        manifest_crud:

    Returns:

    """
    manifest_crud.select_database("FOUNDRY")
    fn_import_tasks_entity = manifest_crud.read(
        filters=[("fn_type", "eq", "ImportTasks")]
    )
    allowed = True
    for entity in fn_import_tasks_entity:
        if entity["state"] in ["new", "ip"]:
            allowed = False

    return allowed


def clear_fn_import_tasks(manifest_crud):
    """
    On application start if there are import tasks with state "ip" they must be broken clear them
    Args:
        manifest_crud:

    Returns:

    """
    manifest_crud.select_database("FOUNDRY")
    fn_import_tasks_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "ImportTasks")]
    )
    for entity in fn_import_tasks_entities:
        manifest_crud.delete(entity["id"])


def create_fn_annotation_link_entity(manifest_crud, annotations):
    """

    Args:
        manifest_crud:
        annotations:

    Returns:

    """
    manifest_crud.select_database("FOUNDRY")
    fn_annotation_link_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "AnnotationLink")]
    )
    for i, annotation in enumerate(annotations):
        manifest_crud.select_database("FOUNDRY")
        existing_link = [
            x for x in fn_annotation_link_entities if x["sg_id"] == annotation["id"]
        ]
        if existing_link:
            manifest_crud.delete(existing_link[-1]["id"])
        fn_annotation_link_entity = {
            "id": "__UNIQUE__",
            "sg_id": annotation["id"],
            "fn_type": "AnnotationLink",
            "note_reply_index": i,
            "localize_path": annotation["localize_path"],
            "created_at": annotation["created"],
        }
        manifest_crud.create(fn_annotation_link_entity)


def create_sg_manifest_notes(parent_item, sg_instance, manifest_crud):
    """Repeated function to unpack all required notes for addition to SG manifest.

    Args:
        parent_item (QObject): parent fn_model.TreeItem
        sg_instance (object): SG instance from SgInstancePool
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget.tree_panel

    Returns:
        (int) : id of the created SG manifest

    """
    # todo simplify with sg.note_thread_read
    manifest_crud.select_database("SG")
    all_notes = []
    note_ids = []
    if parent_item.get("notes"):
        note_ids = [x["id"] for x in parent_item.get("notes")]
    open_note_ids = []
    if parent_item.get("open_notes"):
        open_note_ids = [x["id"] for x in parent_item.get("open_notes")]
    all_notes.extend(note_ids)
    all_notes.extend(open_note_ids)
    if all_notes:
        retrieved_notes = sg_get_req_entity_details(
            sg_instance, "Note", list(set(all_notes))
        )
        attachment_ids = []
        for n in retrieved_notes:
            if n["attachments"]:
                attachment_ids.extend([x["id"] for x in n["attachments"]])
            manifest_crud.select_database("SG")
            manifest_crud.upsert(n)
            create_sg_manifest_replies(n, sg_instance, manifest_crud)
        if attachment_ids:
            annotations = sg_download_annotations(
                sg_instance, attachment_ids, manifest_crud.get_database_directory()
            )
            if annotations:
                create_fn_annotation_link_entity(manifest_crud, annotations)


def create_sg_manifest_replies(note_entity, sg_instance, manifest_crud):
    """Repeated function to unpack all required replies for addition to SG manifest.

    Args:
        note_entity (QObject): parent fn_model.TreeItem
        sg_instance (object): SG instance from SgInstancePool
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget.tree_panel

    Returns:
        (int) : id of the created SG manifest

    """
    # todo simplify with sg.note_thread_read
    manifest_crud.select_database("SG")
    reply_ids = [x["id"] for x in note_entity.get("replies")]
    if reply_ids:
        attachment_ids = []
        retrieved_replies = sg_get_req_entity_details(sg_instance, "Reply", reply_ids)
        for n in retrieved_replies:
            if n.get("attachments", None):
                attachment_ids.extend([x["id"] for x in n["attachments"]])
            manifest_crud.select_database("SG")
            manifest_crud.upsert(n)
        if attachment_ids:
            annotations = sg_download_annotations(
                sg_instance, attachment_ids, manifest_crud.get_database_directory()
            )
            if annotations:
                create_fn_annotation_link_entity(manifest_crud, annotations)


def create_manifest_entities(parent_item, sg_instance, manifest_crud):
    """Create a mirror of a SG entity into SG manifest. Include all required notes. Note this copies all feilds for
    the entity for the sake of visibility and customization this is likely overkill and could be restricted to only
    required downstream fields if scalability issues arise __CUSTOMIZE__

    Args:
        parent_item (QObject): parent fn_model.TreeItem
        sg_instance (object): SG instance from SgInstancePool
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget.tree_panel

    Returns:

    """
    UPDATE_SIGNALS.details_text.emit(False, "Synchronizing Manifests...")
    manifest_crud.select_database("SG")

    id = parent_item.data["id"]
    item_data = sg_get_req_entity_details(sg_instance, parent_item.node_type, [id])[-1]

    if parent_item.node_type == "Playlist":
        item_data["sg_sort_order"] = sg_get_playlist_sort_order(
            sg_instance, item_data["id"]
        )
        version_ids = [x["id"] for x in item_data["versions"]]
        if version_ids:
            versions = sg_get_req_entity_details(sg_instance, "Version", version_ids)
            for version in versions:
                UPDATE_SIGNALS.details_text.emit(
                    False, "Processing Playlist version {}".format(version["id"])
                )
                manifest_crud.select_database("SG")
                manifest_crud.upsert(version)
                create_sg_manifest_notes(version, sg_instance, manifest_crud)

    if parent_item.node_type == "Cut":
        cutitem_ids = [
            x["id"] for x in item_data["cut_items"] if "offline_" not in x["name"]
        ]

        if cutitem_ids:
            item_data["cut_items"] = sg_get_req_entity_details(
                sg_instance, "CutItem", cutitem_ids
            )
            cut_version_links = [x.get("version") for x in item_data["cut_items"]]
            cut_version_ids = [x.get("id") for x in cut_version_links]

            # Custom offline version addition
            offline_version = item_data.get("version")
            if offline_version:
                offline_version_id = offline_version.get("id")
                cut_version_ids.append(offline_version_id)

            cut_versions = sg_get_req_entity_details(
                sg_instance, "Version", cut_version_ids
            )
            for cut_version in cut_versions:
                UPDATE_SIGNALS.details_text.emit(
                    False, "Processing Cut version {}".format(cut_version["id"])
                )
                manifest_crud.select_database("SG")
                manifest_crud.upsert(cut_version)
                create_sg_manifest_notes(cut_version, sg_instance, manifest_crud)

    # __CUSTOMIZE__ studio can add extra handling here for seq, shot, latest etc
    #if parent_item.node_type == "Sequence":

    manifest_crud.select_database("SG")
    manifest_crud.upsert(item_data)

    create_sg_manifest_notes(item_data, sg_instance, manifest_crud)

    if item_data.get("attachments", None):
        annotations = sg_download_annotations(
            sg_instance,
            [x["id"] for x in item_data["attachments"]],
            manifest_crud.get_database_directory(),
        )
        if annotations:
            create_fn_annotation_link_entity(manifest_crud, annotations)

    UPDATE_SIGNALS.details_text.emit(
        False, "Finished synchronizing Manifests for {}...".format(item_data["type"])
    )
    return item_data["id"]


def check_localized(parent_item, manifest_crud, non_context_items):
    """fn_model.LazyTreeModel live column checker. This updates the tree model and UI to display if an item is
    localized. It uses the Foundry manifest to retrieve localization strategy entities and check if the entity is marked
    as localized.

    Args:
        parent_item (QObject): parent fn_model.TreeItem
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget.tree_panel
        non_context_items (list): Skip items in the provided. globals set in fn_globals.NON_CONTEXT_ENTITIES

    Returns:
        (str) : state of the content

    """
    if parent_item.node_type in non_context_items:
        return ""
    id = parent_item.data["id"]
    localized = "X"
    manifest_crud.select_database("FOUNDRY")
    fn_localized_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "LocalizeStrategy"), ("localized", "eq", True)]
    )
    fn_version_link_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "VersionLink")]
    )
    for localized_entity in fn_localized_entities:
        if localized_entity["sg_version_id"] == id:
            localized = localized_entity["localize_type"]
    for version_link in fn_version_link_entities:
        if version_link["sg_id"] == id:
            localized = "Download"
    if localized == "Download":
        localized = "✓"

    return localized


def check_edits(parent_item, manifest_crud, non_context_items):
    """fn_model.LazyTreeModel live column checker. This updates the tree model and UI to display if an item is
    edited. It uses the Foundry manifest to retrieve and count change entities.

    Args:
        parent_item (QObject): parent fn_model.TreeItem
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget.tree_panel
        non_context_items (list): Skip items in the provided. globals set in fn_globals.NON_CONTEXT_ENTITIES

    Returns:
        (int) : count of edits for related localized content

    """
    if parent_item.node_type in non_context_items:
        return ""
    id = parent_item.data["id"]
    manifest_crud.select_database("FOUNDRY")
    fn_change_entities = manifest_crud.read(
        filters=[
            (
                "fn_type",
                "in",
                ["NewNote", "StatusChange", "NoteReply"],
            )
        ]
    )
    fn_version_link_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "VersionLink")]
    )
    changes = []
    parent_version = [x for x in fn_version_link_entities if x["sg_id"] == id]
    if parent_version:
        for entity in fn_change_entities:
            for key, value in entity.items():
                if value in parent_version[-1]["sg_version_ids"]:
                    changes.append(value)
    else:
        for entity in fn_change_entities:
            for key, value in entity.items():
                if value == id:
                    changes.append(value)
    return len(changes)


def check_sync(parent_item, manifest_crud, non_context_items):
    """fn_model.LazyTreeModel live column checker. This updates the tree model and UI to display if an item is
    synced.Checks Shotgrid vs SG manifest entities to ensure localized content is up to date

    Args:
        parent_item (QObject): parent fn_model.TreeItem
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget.tree_panel
        non_context_items (list): Skip items in the provided. globals set in fn_globals.NON_CONTEXT_ENTITIES

    Returns:
        (str) : state of sync

    """
    if parent_item.node_type in non_context_items:
        return ""
    manifest_crud.select_database("SG")
    fn_sg_manifest_entity = manifest_crud.read(
        filters=[("id", "eq", parent_item.data["id"])]
    )
    if fn_sg_manifest_entity:
        fn_sg_manifest_entity = fn_sg_manifest_entity[-1]
        if str(parent_item.data.get("updated_at")) == str(
            fn_sg_manifest_entity.get("updated_at")
        ):
            if not parent_item.data.get("updated_at"):
                return ""
            return "="
        else:
            return "<"
    else:
        return ""
