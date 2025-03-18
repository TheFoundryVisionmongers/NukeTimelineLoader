import os
import hiero

from nt_loader.fn_workers import UPDATE_SIGNALS
from nt_loader.fn_helpers import convert_media_path_to_map, crop_edited_image
from nt_loader.fn_ui import QColor


def hiero_capture_annotation(version_id):
    """
    Capture image of viewer with annotation cropping non required elements. This formats the filename for SG
    returns:
        (str) path to temporary annotation file, (str) path to sg named annotation file
    """
    seq = hiero.ui.activeSequence()
    timeline_frame = hiero.ui.currentViewer().time()
    track_items = seq.trackItemsAt(hiero.ui.currentViewer().time())
    version_track_item = [x for x in track_items if hiero_get_clip_sg_id(x.source()) == version_id]
    if not version_track_item:
        UPDATE_SIGNALS.details_text(True, "Incorrect track item selected for annotation Aborting")
        return None, None
    # added extra frame to end as hiero starts at frame 0
    frame = timeline_frame - version_track_item[-1].handleInTime() + 1
    no_edit_filename = "temp_non_edit_frame.png"
    temp_annotation_file_name = "temp_annotation.png"
    annotation_file_name = f"annot_version_{str(version_id)}.{str(frame)}.png"
    annotation_directory = os.path.join(
        os.environ.get("SG_LOCALIZE_DIR"), "annotations"
    )
    os.makedirs(annotation_directory, exist_ok=True)
    temp_non_edit_frame_path = os.path.join(annotation_directory, no_edit_filename)
    temp_annotation_file_path = os.path.join(
        annotation_directory, temp_annotation_file_name
    )
    annotation_file_path = os.path.join(annotation_directory, annotation_file_name)
    viewer = hiero.ui.currentViewer()
    player = viewer.player(0)
    player.setProxyResolution(hiero.ui.Player.ProxyResolution.eProxyFull)
    player.zoomToFit()
    # Ensure annotation is displayed. Set to False to grab without annotation
    viewer.setOverlaysShown(False)
    viewer.image().save(temp_non_edit_frame_path, "PNG")
    viewer.setOverlaysShown(True)
    viewer.image().save(temp_annotation_file_path, "PNG")
    # compare images using openCV ensure time code widget is removed. NOTE: if frame code widget is in frame it will be
    # captured
    crop_edited_image(
        temp_non_edit_frame_path, temp_annotation_file_path, annotation_file_path
    )
    return temp_annotation_file_path, annotation_file_path

def hiero_import_tags(tag_data):
    """Creates SG tags for loaded project

    Args:
        tag_data (list): of dict containing icon paths and names for tags
    """
    projects = hiero.core.projects()
    project = projects[-1]
    tags_bin = project.tagsBin()
    existing_tags = [x.name() for x in tags_bin.items()]
    existing_tags = list(set(existing_tags))
    for tag_info in tag_data:
        tag_name = tag_info["name"]
        icon_path = tag_info["icon_path"]
        if tag_name not in existing_tags:
            tag = hiero.core.Tag(tag_name)
            tag.setIcon(icon_path)
            tags_bin.addItem(tag)


def hiero_get_or_create_bin(project, bin_name):
    """Select or create desired bin.

    Args:
        project (_type_): _description_
        bin_name (_type_): _description_

    Returns:
        (object): created or selected hiero.core.Bin
    """
    target_bin = None
    root_bin = project.clipsBin()

    for bin in root_bin.bins():
        if bin.name() == bin_name:
            target_bin = bin

    if not target_bin:
        named_bin = hiero.core.Bin(bin_name)
        root_bin.addItem(named_bin)
        target_bin = named_bin

    return target_bin


def hiero_get_or_create_sequence(target_bin, seq_name):
    """Select or create desired sequence.

    Args:
        target_bin (str): name of bin to create in
        seq_name (str): name of sequence to create

    Returns:
        (object): created or selected hiero.core.Sequence
    """
    projects = hiero.core.projects()
    project = projects[-1]
    sequences = hiero.core.findItemsInProject(project, hiero.core.Sequence)
    existing_sequence = None
    for s in sequences:
        if s.name() == seq_name:
            existing_sequence = s

    if not existing_sequence:
        sequence = hiero.core.Sequence(seq_name)
        target_bin.addItem(hiero.core.BinItem(sequence))
        existing_sequence = sequence
    return existing_sequence


# TODO refactor below functions to utilize hiero.core.find_items.
def hiero_get_clips_and_paths(target_bin, type="paths"):
    """Create a list of clips objects or the path strings in clips depending on selected type argument

    Args:
        target_bin (Hiero.Core.Clip): name of bin to search in
        type (str, optional): defaults to paths=list of paths in clips, obj=list of hiero.core.Clip objs

    Returns:
        (list): of items depending on selected type argument
    """
    existing_clips = []
    for b in target_bin.items():
        for c in b.items():
            try:
                if type == "obj":
                    existing_clips.append(c.item())
                if type == "paths":
                    existing_clips.append(
                        os.path.normpath(c.item().mediaSource().firstpath())
                    )
            except AttributeError:
                pass
    return existing_clips


def hiero_get_clip_with_path(target_bin, path):
    """Search for a hiero.core.Clip object by path

    Args:
        target_bin (Hiero.Core.Bin): name of bin to search in
        path (str): path to media for retrieval of clip

    Returns:
        (list): of hiero.core.Clip objects
    """
    existing_clips = []
    path = os.path.normpath(path)
    for b in target_bin.items():
        for c in b.items():
            try:
                if os.path.normpath(c.item().mediaSource().firstpath()) == path:
                    existing_clips.append(c.item())
            except AttributeError:
                pass
    return existing_clips


def hiero_get_clips_with_ids(target_ids, bin_name="Versions"):
    """Search clip tags for clips with required ids

    Args:
        target_ids (list): of int ids to retrieve clips for
        bin_name (str, optional): name of bin to search. Defaults to "Versions".

    Returns:
        (list): of hiero.core.Clip objects
    """
    existing_clips = []
    target_bin = hiero_get_bin(bin_name)
    for b in target_bin.items():
        for c in b.items():
            try:
                if int(hiero_get_clip_sg_id(c.item())) in target_ids:
                    existing_clips.append(c.item())
            except AttributeError:
                pass
    return existing_clips


def hiero_get_bin_item_from_sg_id(bin_name, sg_id):
    """Search clip tags for bin items with required ids

    Args:
        bin_name (str, optional): name of bin to search. Defaults to "Versions".
        sg_id (int): id in clip tags to identify bin item

    Returns:
        (object): found hiero.core.BinItem object
    """
    target_bin = hiero_get_bin(bin_name)
    bin_item = []
    for b in target_bin.items():
        for c in b.items():
            if hiero_get_clip_sg_id(c.item()) == sg_id:
                bin_item.append(b)
    if bin_item:
        return bin_item[-1]


def hiero_add_base_tags(clip, version_entity, color_map, is_edited=False):
    """Add tags to clip for use in loader system

    Args:
        clip (object): hiero.core.Clip object to add tags to
        version_entity (dict): SG manifest version entity
        color_map (dict): Foundry manifest base entity color map information containing SG status colors
        is_edited (bool, optional): sets is_edited tag for clip . Defaults to False.

    Returns:
        (str): Hex color to assign to clip or trackitems
    """
    if not is_edited:
        tag = hiero_get_sg_tag(version_entity["sg_status_list"])
        color = hiero_get_status_color_from_tag(
            version_entity["sg_status_list"], color_map
        )
        sg_id_tag = hiero.core.Tag("_sg_id")
        sg_id_tag.setIcon("icons:TagNote.png")
        sg_id_tag.setNote(str(version_entity["id"]))
        refresh_tags = [clip.removeTag(x) for x in clip.tags()]
        clip.addTag(sg_id_tag)
        is_edited_tag = hiero.core.Tag("_is_edited")
        is_edited_tag.setNote(str(False))
        clip.addTag(is_edited_tag)
        clip.addTag(tag)
        return color
    else:
        edit_color = QColor(255, 255, 0)
        return edit_color


def hiero_get_clip_sg_id(clip):
    """Retrieve clips sg_id tag

    Args:
        clip (object): hiero.core.Clip object to retrieve sg_id from

    Returns:
        (int): the sg_id applied to this clip
    """
    for tag in clip.tags():
        if tag.name() == "_sg_id":
            return int(tag.note())


def hiero_get_clip_is_edited(clip):
    """Retrieve is edited state from clip

    Args:
        clip (object): hiero.core.Clip object to get edited state

    Returns:
        (bool): the edit state of the clip
    """
    for tag in clip.tags():
        if tag.name() == "_is_edited":
            return bool(tag.note())


def hiero_set_clip_is_edited(clip, edited=True):
    """Set the tag is_edited clip tag

    Args:
        clip (object): hiero.core.Clip object to set edited state
        edited (bool, optional): Defaults to True.
    """
    for tag in clip.tags():
        if tag.name() == "_is_edited":
            tag.setNote(str(edited))


def hiero_get_bin(bin_name):
    projects = hiero.core.projects()
    project = projects[-1]
    target_bin = None
    root_bin = project.clipsBin()
    for bin in root_bin.bins():
        if bin.name() == bin_name:
            target_bin = bin
    return target_bin


def hiero_get_track_items_from_sg_id(sg_id):
    """Retrieve track items from sg_id

    Args:
        sg_id (int): sg_id to retrieve track items from

    Returns:
        (list): of hiero.core.TrackItem objects related to sg_id
    """
    projects = hiero.core.projects()
    project = projects[-1]
    existing_track_items = hiero.core.find_items.findItemsInProject(
        project, hiero.core.TrackItem
    )
    selected_track_items = []
    for track_item in existing_track_items:
        if hiero_get_clip_sg_id(track_item.source()) == sg_id:
            selected_track_items.append(track_item)
    return selected_track_items


def hiero_get_track_items_from_clip(clip):
    """Retrieve track items from clip

    Args:
        clip (object): hiero.core.Clip object to retrieve track items from

    Returns:
        (list): of hiero.core.TrackItem objects related to clip
    """
    projects = hiero.core.projects()
    project = projects[-1]
    existing_track_items = hiero.core.find_items.findItemsInProject(
        project, hiero.core.TrackItem
    )
    selected_track_items = []
    for track_item in existing_track_items:
        if track_item.source() == clip:
            selected_track_items.append(track_item)
    return selected_track_items


def hiero_get_status_tag_from_clip(clip):
    """Retrieve SG status from clip

    Args:
        clip (object): hiero.core.Clip object to retrieve SG status

    Returns:
        (str): SG status from clip
    """
    for tag in clip.tags():
        status_tag = hiero_get_sg_tag(tag.name())
        if status_tag:
            return status_tag


def hiero_get_sg_tag(tag_name):
    """Retrieve hiero tag from SG tag name

    Args:
        tag_name (str): SG tag name

    Returns:
        (object) : hiero.core.Tag object relating to SG tag name
    """
    projects = hiero.core.projects()
    project = projects[-1]
    tags_bin = project.tagsBin()
    tag = [x for x in tags_bin.items() if x.name() == tag_name]
    if tag:
        return tag[-1]
    else:
        return False


def hiero_get_status_color_from_tag(tag_name, color_map):
    """Retrieve tht HEX color string from a tag

    Args:
        tag_name (str): SG status tag name
        color_map (dict): Foundry manifest base entity color map information containing SG status colors

    Returns:
        (str): Hex color
    """
    for status in color_map:
        if status["code"] == tag_name:
            if status["bg_color"]:
                color1, color2, color3 = (int(x) for x in status["bg_color"].split(","))
                color = str(QColor(color1, color2, color3).name())
                return color


def hiero_set_track_item_tag(track_item, tag_name, color_map, edit=False):
    """Apply tag to trackitem

    Args:
        track_item (object): hiero.core.TrackItem object to tag
        tag_name (str): SG tag name
        color_map (dict): Foundry manifest base entity color map information containing SG status
        edit (bool, optional): Defaults to False.
    """
    tag = hiero_get_sg_tag(tag_name)
    refresh_tags = [track_item.removeTag(x) for x in track_item.tags()]
    sg_id = hiero_get_clip_sg_id(track_item.source())
    color = hiero_get_status_color_from_tag(tag_name, color_map)
    bin_item = hiero_get_bin_item_from_sg_id("Versions", sg_id)
    track_item.addTag(tag)
    if hiero_get_clip_is_edited(track_item.source()):
        edit_color = QColor(255, 255, 0)
        bin_item.setColor(edit_color)
    if edit:
        hiero_set_clip_is_edited(track_item.source())
        edit_color = QColor(255, 255, 0)
        bin_item.setColor(edit_color)
    else:
        hiero_set_clip_is_edited(track_item.source(), False)
        bin_item.setColor(color)


def hiero_get_video_track_index(sequence, video_track):
    """Find the index of the provided hiero.core.VideoTrack object

    Args:
        sequence (object): hiero.core.Sequence object
        video_track (object): hiero.core.VideoTrack object

    Returns:
        (int): the index of the video track in the sequence
    """
    return sequence.videoTracks().index(video_track)


def hiero_add_files_to_bin(manifest_crud, fn_entity_ids, color_map, sg_instance):
    """Add files to the hiero bin from the pre-created Foundry manifest entities
    This is one of the main working functions of this tool and is commented to be as verbose as possible

    Args:
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
        fn_entity_ids (list): of int FN manifest version ids
        color_map (dict): Foundry manifest base entity color map information containing SG status
        sg_instance (object): SG instance from SgInstancePool

    Returns:
        (object): hiero.core.Bin object in which the files have been added
    """
    manifest_crud.select_database("FOUNDRY")
    # collect foundry options and icon information from foundry manifest
    fn_base_entity = manifest_crud.read(filters=[("id", "eq", 0)])[-1]
    color_map = fn_base_entity["color_map"]
    options = fn_base_entity["options"]

    # collect the pre created link entities from the foundry manifest
    fn_version_link_entities = manifest_crud.read(
        filters=[("id", "in", fn_entity_ids), ("fn_type", "eq", "VersionLink")]
    )
    fn_annotation_link_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "AnnotationLink")]
    )
    fn_localized_version_entities = manifest_crud.read(
        filters=[("fn_type", "eq", "LocalizeStrategy"), ("localized", "eq", True)]
    )
    # Switch to the SG manifest
    manifest_crud.select_database("SG")
    required_sg_version_ids = []
    # isolate and collect entity information based on the version ids in the foundry VersionLink entity
    [
        required_sg_version_ids.extend(x)
        for x in [y["sg_version_ids"] for y in fn_version_link_entities]
    ]
    required_sg_version_ids = list(set(required_sg_version_ids))
    sg_manifest_version_entities = manifest_crud.read(
        filters=[("id", "in", required_sg_version_ids)]
    )
    # Use the existing Hiero project
    projects = hiero.core.projects()
    project = projects[-1]
    # Create a Versions folder in the project Bin or get the existing
    versions_bin = hiero_get_or_create_bin(project, "Versions")
    for fn_entity in fn_version_link_entities:
        parent_bin_name = fn_entity["sg_type"]
        if parent_bin_name == "Version":
            parent_bin = versions_bin
        else:
            parent_bin = hiero_get_or_create_bin(project, parent_bin_name)
    # Check existing clips and paths. This avoids re-importing clips that already exist in versions
    existing_clip_paths = hiero_get_clips_and_paths(versions_bin)
    broken_version_link = []
    # iterate over required SG entities to provide supplemental information for clip creation
    for sg_entity in sg_manifest_version_entities:
        # __CUSTOMIZE__ Safety check for versions with duplicate file names . Rarely a studio has non-unique version
        # file paths however if your seeing this error alot and content is not importing this is the area that will need
        # change
        try:
            fn_localized_entity = [
                x
                for x in fn_localized_version_entities
                if x["sg_version_id"] == sg_entity["id"]
            ][-1]
        except IndexError:
            UPDATE_SIGNALS.details_text.emit(
                True,
                "DUPLICATE VERSION FOUND !!! please check the following in SG code:{} id:{}".format(
                    sg_entity["code"], sg_entity["id"]
                ),
            )
            continue
        # Get note, reply  information and annotations to be added to bin/timeline downstream
        if sg_entity.get("notes", None):
            note_ids = [x["id"] for x in sg_entity["notes"] if x]
            sg_manifest_note_entities = manifest_crud.read(
                filters=[("id", "in", note_ids)]
            )
            replies = []
            for rep in sg_manifest_note_entities:
                if rep.get("replies", None):
                    replies.extend(rep.get("replies"))

            reply_ids = [x.get("id") for x in replies if x]
            sg_manifest_reply_entities = manifest_crud.read(
                filters=[("id", "in", reply_ids)]
            )
            attachments = []
            [
                attachments.extend(x.get("attachments", []))
                for x in sg_manifest_note_entities
            ]
            [
                attachments.extend(x.get("attachments", []))
                for x in sg_manifest_reply_entities
            ]
            # Attachments point to annotations
            if attachments:
                # if there are annotations get or make a new bin folder for them
                annotation_bin = hiero_get_or_create_bin(project, "Annotations")
                if options.get("Import SG annotations to timeline", False):
                    for att in attachments:
                        annotation_link_entity = [
                            x
                            for x in fn_annotation_link_entities
                            if x["sg_id"] == att["id"]
                        ]
                        if annotation_link_entity:
                            annotation_localized_path = annotation_link_entity[-1][
                                "localize_path"
                            ]
                            current_clip = hiero_get_clip_with_path(
                                annotation_bin,
                                os.path.normpath(annotation_localized_path),
                            )
                            if not current_clip:
                                annotation_clip = hiero.core.Clip(
                                    annotation_localized_path
                                )
                                refresh_tags = [
                                    annotation_clip.removeTag(x)
                                    for x in annotation_clip.tags()
                                ]
                                # embed SG ids in tags for later use
                                sg_id_tag = hiero.core.Tag("_sg_id")
                                sg_id_tag.setIcon("icons:TagNote.png")
                                sg_id_tag.setNote(str(sg_entity["id"]))
                                annotation_clip.addTag(sg_id_tag)
                                bin_item = hiero.core.BinItem(annotation_clip)
                                annotation_bin.addItem(bin_item)

        # File import using chosen foundry LocalizeStrategy entities
        localize_map = {
            "Download": "download_file_path",
            "Copy": "copy_file_path",
            "Direct": "direct_file_path",
        }
        localize_key = localize_map[fn_localized_entity["localize_type"]]
        current_clip = hiero_get_clip_with_path(
            versions_bin, os.path.normpath(fn_localized_entity[localize_key])
        )
        # check if the clip for import is existing ensure no alteration if the clip has edits applied
        if current_clip:
            c_clip = current_clip[-1]
            if hiero_get_clip_is_edited(c_clip):
                hiero_add_base_tags(c_clip, sg_entity, color_map, is_edited=True)
        # Triple check that the clip is viable for import
        if (
            os.path.normpath(fn_localized_entity[localize_key])
            not in existing_clip_paths
        ):
            # Safety mechanism to avoid silent failure in import these can arise from hiero trying to import
            # incorrectly formatted media. will report the exception to the UI
            try:
                # import clip content from chosen LocalizeStrategy path to media
                # is passed through path mapping function which by default is disabled
                clip = hiero.core.Clip(
                    convert_media_path_to_map(fn_localized_entity[localize_key])
                )
                # __CUSTOMIZE__ Custom import configuration. Placeholder for studio to apply extra information to clip and
                # or bin item potentially useful for extra tag, colorspace, etc
                if options.get("Custom import configuration", False):
                    UPDATE_SIGNALS.details_text.emit(
                        True,
                        "Custom import configuration not implemented. \nSearch fn_hiero_func.py #__CUSTOMIZE__ Custom import configuration. ",
                    )
                color = hiero_add_base_tags(clip, sg_entity, color_map)
                bin_item = hiero.core.BinItem(clip)
                bin_item.setColor(color)
                versions_bin.addItem(bin_item)

            except TypeError:
                UPDATE_SIGNALS.details_text.emit(
                    True,
                    "Clip failed to import - {}".format(
                        fn_localized_entity[localize_key]
                    ),
                )
                broken_version_link.append(sg_entity["id"])
                continue

    # Safety mechanism if a clip was not imported properly or is unsupported . Delete the version link entry to avoid
    # incorrect timeline import WARNING will leave stranded versions
    if broken_version_link:
        manifest_crud.select_database("FOUNDRY")
        broken_fn_ids = []
        for link in fn_version_link_entities:
            for v in link["sg_version_ids"]:
                if v in broken_version_link:
                    broken_fn_ids.append(link["id"])
        broken_fn_ids = list(set(broken_fn_ids))
        broken_fn_entities = [
            x for x in fn_version_link_entities if x["id"] in broken_fn_ids
        ]
        for broken in broken_fn_entities:
            UPDATE_SIGNALS.details_text.emit(
                True,
                "{} Version Link broken - {}\n!!REMOVING!!".format(
                    broken["sg_type"], broken["sg_name"]
                ),
            )
            manifest_crud.delete(broken["id"])
    # iterate over all viable track/bin/clips to ensure correct tagging. happens on manifest sync also
    hiero_update_changed_items(manifest_crud)
    return parent_bin


def hiero_add_version_links_to_timeline(manifest_crud, fn_entity_ids):
    """Add sequences and or video tracks based on pre-created Foundry VersionLink manifest entity

    Args:
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
        fn_entity_ids (list): of int Foundry manifest VersionLink ids
    """
    manifest_crud.select_database("FOUNDRY")
    # collect foundry options and icon information from foundry manifest
    fn_base_entity = manifest_crud.read(filters=[("id", "eq", 0)])[-1]
    options = fn_base_entity["options"]
    # collect the pre-created foundry VersionLink entities related to the required timelines
    fn_version_link_entities = manifest_crud.read(
        filters=[("id", "in", fn_entity_ids), ("fn_type", "eq", "VersionLink")]
    )
    note = "All sequences added!"
    # iterate through the VersionLinks and create sequences and video tracks based on their type
    for entity in fn_version_link_entities:
        projects = hiero.core.projects()
        project = projects[-1]
        target_bin = hiero_get_bin(entity["sg_type"])

        if entity["sg_type"] != "Version":
            # checks if the Options for import to existing sequence or creates a new sequence if not
            if options.get("Import to loaded sequence", False):
                note = "All Tracks added to selected sequence"
                sequence = hiero.core.find_items.findItemsInProject(
                    project, hiero.core.Sequence
                )
                if not sequence:
                    options["Import to loaded sequence"] = False
                if sequence:
                    sequence = hiero.ui.activeSequence()

            if not options.get("Import to loaded sequence"):
                sequence = hiero_get_or_create_sequence(target_bin, entity["sg_name"])

        clips = hiero_get_clips_with_ids(entity["sg_version_ids"])

        # __CUSTOMIZE__ Playlist timeline sequence creation
        if entity["sg_type"] == "Playlist":
            video_track = hiero.core.VideoTrack(entity["sg_name"])
            sequence.addTrack(video_track)
            video_track_index = hiero_get_video_track_index(sequence, video_track)
            time = 0
            for id in entity["sg_version_ids"]:
                for clip in clips:
                    clip_sg_id = hiero_get_clip_sg_id(clip)
                    if id == clip_sg_id:
                        sequence.addClip(clip, time, video_track_index)
                        track_items = hiero_get_track_items_from_clip(clip)
                        tag = hiero_get_status_tag_from_clip(clip)
                        [track_item.addTag(tag) for track_item in track_items]

                        time += clip.duration()
            if options.get("Import SG annotations to timeline", False):
                hiero_create_annotation_tracks(sequence, video_track)

        # __CUSTOMIZE__ Cut timeline sequence creation
        if entity["sg_type"] == "Cut":
            # Default to SG cuts see below for area to add in alternate approaches
            if options.get("Attached cut file import strategy") == "Used SG Cuts":
                cut_lead_in = int(options["Cut lead in frames"])
                # Create a new sequence with the correct frame rate and timecode start
                sequence_fps = (
                    entity.get("fps") or 24.0
                )  # Default to 24 fps if not specified
                sequence_tc_start = entity.get("timecode_start_text") or "00:00:00:00"

                sequence.setFramerate(sequence_fps)
                sequence.setTimecodeStart(
                    hiero_timecode_to_frames(sequence_fps, sequence_tc_start.split(":"))
                )

                manifest_crud.select_database("SG")
                sg_manifest_entity = manifest_crud.read(
                    filters=[("id", "eq", entity["sg_id"])]
                )[-1]
                cut_items = sg_manifest_entity.get("cut_items")
                cut_items.sort(key=lambda x: x.get("cut_order", 0))

                # __CUSTOMIZE__ offline track handling. Some studio use the version of a cut to contain client or
                # offline media . By default, if there is a version attached to the top level of a cut this will import
                # its content as a separate video track
                if sg_manifest_entity.get("version"):
                    offline_clip = hiero_get_clips_with_ids(
                        [sg_manifest_entity["version"]["id"]], bin_name="Versions"
                    )[-1]
                    sequence.addClip(offline_clip, 0, 0)

                # Create a video track
                video_track = hiero.core.VideoTrack(entity["sg_name"])
                sequence.addTrack(video_track)
                for cut_item in cut_items:
                    version_id = cut_item["version"]["id"]
                    clip = hiero_get_clips_with_ids([version_id], bin_name="Versions")[
                        -1
                    ]

                    # If the media has embedded timecode, use it; otherwise, set to 00:00:00:00
                    try:
                        media_start_tc = (
                            clip.mediaSource().timecodeStart() - cut_lead_in
                        )
                    except AttributeError:
                        media_start_tc = (
                            0  # Default to frame 0 if no timecode is available
                        )
                    clip.setTimecodeStart(media_start_tc)

                    # Create a TrackItem
                    track_item = video_track.createTrackItem(clip.name())
                    track_item.setSource(clip)
                    # Set source in/out points
                    cut_item_in = cut_item.get("cut_item_in") - cut_lead_in - 1
                    cut_item_out = cut_item.get("cut_item_out") - cut_lead_in - 1
                    edit_in = cut_item.get("edit_in") - 1
                    edit_out = cut_item.get("edit_out") - 1
                    track_item.setTimes(edit_in, edit_out, cut_item_in, cut_item_out)
                    video_track.addTrackItem(track_item)
            else:
                # __CUSTOMIZE__ Alternate Cut File. If a cut has an embeded OTIO or EDL build logic here
                UPDATE_SIGNALS.details_text.emit(
                    True,
                    "Alternate Cut file import not implemented. \nSearch fn_hiero_func.py #__CUSTOMIZE__ Alternate Cut File. ",
                )
                return

            if options.get("Import SG annotations to timeline", False):
                hiero_create_annotation_tracks(sequence, video_track)

        # __CUSTOMIZE__ single version import to timeline. Default is to only import to bin and have the user manually
        # place in sequence
        if entity["sg_type"] == "Version":
            note = "Version {} not added to timeline. Browse to Bin Versions and add to required sequence".format(
                entity["sg_name"]
            )

        # __CUSTOMIZE__ add studio specific VersionLink entity unpacking to drive timeline for seq, shot, latest etc
        #if entity["sg_type"] == "Sequence":
        # add logic for sequence timeline based construction

    hiero_update_changed_items(manifest_crud)
    UPDATE_SIGNALS.details_text.emit(False, note)


def hiero_create_annotation_tracks(sequence, video_track):
    """Sub function of hiero_add_version_links_to_timeline to add video tracks for annotations if required in options

    Args:
        sequence (object): hiero.core.Sequence object to add annotations to
        video_track (object): hiero.core.VideoTrack object to add annotations to
    """

    track_item_map = {"{}_annotations_{}".format(video_track.name(), 0): []}

    time = 0
    for existing_track_item in video_track.items():
        clip = existing_track_item.source()
        clip_sg_id = hiero_get_clip_sg_id(clip)
        a_clips = hiero_get_clips_with_ids([clip_sg_id], bin_name="Annotations")
        if a_clips:
            for index, a in enumerate(a_clips):
                if index > 0:
                    track_item_map.update(
                        {"{}_annotations_{}".format(video_track.name(), index): []}
                    )

            for index, a in enumerate(a_clips):
                track_item = hiero.core.TrackItem(a.name(), hiero.core.TrackItem.kVideo)
                frame = int(a.name().split("_")[-1].replace("Frame", ""))
                track_item.setSource(a)
                track_item.setTimelineIn(time + frame)
                track_item.setTimelineOut(time + frame)
                track_item_map[
                    "{}_annotations_{}".format(video_track.name(), index)
                ].append(track_item)

        time += existing_track_item.duration()

    for k, v in track_item_map.items():
        annotation_track = hiero.core.VideoTrack(k)
        for track_item in v:
            annotation_track.addItem(track_item)
        sequence.addTrack(annotation_track)


def hiero_update_changed_items(manifest_crud):
    """Iterate over all clip,binitems and trackitems in project and validate or update their tags

    Args:
        manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
    """
    manifest_crud.select_database("FOUNDRY")
    fn_base_entity = manifest_crud.read(filters=[("id", "eq", 0)])[-1]
    color_map = fn_base_entity["color_map"]
    fn_change_entities = manifest_crud.read(
        filters=[
            (
                "fn_type",
                "in",
                ["NewNote", "StatusChange", "NoteReply"],
            )
        ]
    )
    target_bin = hiero_get_bin("Versions")
    if not target_bin:
        UPDATE_SIGNALS.details_text.emit(
            True,
            "No bin/track items detected! Edit/s will be applied on next import",
        )
        return
    all_bin_items = target_bin.items()
    change_version_ids = [x.get("sg_parent_id") for x in fn_change_entities if x]
    edited_bin_item_ids = [
        hiero_get_clip_sg_id(x.items()[-1].item())
        for x in all_bin_items
        if hiero_get_clip_is_edited(x.items()[-1].item())
    ]
    manifest_crud.select_database("SG")

    # Reset non edited
    for edit in edited_bin_item_ids:
        if edit not in change_version_ids:
            sg_version_entity = manifest_crud.read(filters=[("id", "eq", edit)])[-1]
            clip = hiero_get_clips_with_ids([edit])[-1]
            [clip.removeTag(x) for x in clip.tags()]  # Refresh clip tags
            color = hiero_add_base_tags(clip, sg_version_entity, color_map)
            bin_item = hiero_get_bin_item_from_sg_id("Versions", edit)
            bin_item.setColor(color)
            status_tag = hiero_get_status_tag_from_clip(clip)
            track_items = hiero_get_track_items_from_clip(clip)
            for track_item in track_items:
                [
                    track_item.removeTag(x) for x in track_item.tags()
                ]  # Refresh track tags
                track_item.addTag(status_tag)

    edit_color = QColor(255, 255, 0)
    for change in fn_change_entities:
        for bin_item in all_bin_items:
            clip = bin_item.items()[-1].item()
            current_status = hiero_get_status_tag_from_clip(clip)
            track_items = hiero_get_track_items_from_clip(clip)
            if any(
                [
                    bool(change.get("sg_entity_id") == hiero_get_clip_sg_id(clip)),
                    bool(change.get("sg_parent_id", "") == hiero_get_clip_sg_id(clip)),
                ]
            ):
                bin_item.setColor(edit_color)
                hiero_set_clip_is_edited(clip)
                if change["fn_type"] == "StatusChange":
                    new_status = hiero_get_sg_tag(change["new_status"])
                    if change["sg_type"] == "Note":
                        new_status = current_status
                elif (
                    manifest_crud.read(
                        filters=[("id", "eq", hiero_get_clip_sg_id(clip))]
                    )[-1]["sg_status_list"]
                    != current_status
                ):
                    old_status = manifest_crud.read(
                        filters=[("id", "eq", hiero_get_clip_sg_id(clip))]
                    )[-1]["sg_status_list"]
                    new_status = hiero_get_sg_tag(old_status)

                [
                    clip.removeTag(x)
                    for x in clip.tags()
                    if x.name() == current_status.name()
                ]  # Refresh clip status tag
                clip.addTag(new_status)
                if change["fn_type"] in ["NewNote", "NoteReply"]:
                    bin_item.setColor(edit_color)
                if track_items:
                    for track_item in track_items:
                        [
                            track_item.removeTag(x) for x in track_item.tags()
                        ]  # Refresh track tags
                        track_item.addTag(new_status)

def hiero_register_callbacks(callback_function):
    """
    Register the required callbacks to a function used to bridge qt ui with hiero
    Args:
        callback_function (function): the function in the ui to call on callback event

    Returns:
        (none)

    """
    hiero.core.events.registerInterest(
        hiero.core.events.EventType.kPlaybackClipChanged,
        callback_function,
    )
    hiero.core.events.registerInterest(
        hiero.core.events.EventType.kSelectionChanged,
        callback_function,
    )

def hiero_unregister_callbacks(callback_function):
    """
    Unregister the required callbacks
    Args:
        callback_function (function): the function in the ui to remove from callbacks

    Returns:
        (none)

    """
    hiero.core.events.unregisterInterest(
        hiero.core.events.EventType.kPlaybackClipChanged,
        callback_function,
    )
    hiero.core.events.registerInterest(
        hiero.core.events.EventType.kSelectionChanged,
        callback_function,
    )

def hiero_fire_callback(manifest_crud, event):
    """

    Args:
        event:

    Returns:

    """
    # this can be tricky to diagnose and update uncomment below to get a better idea of the events triggered
    # print("Event fired with type {}, subtype {} and sender {} dir {}".format(event.type, event.subtype, str(event.sender), dir(event.sender)))
    # TODO isolate the crash that can happen when deleting a sequence. Could be another callback for delete sequence
    #  is required to unregister callbacks?
    notes_tab_data = None
    try:
        if event.subtype == "kBin":
            bin_item = event.sender.getSelection()[-1]
            clip = bin_item.items()[-1].item()
            sg_id = hiero_get_clip_sg_id(clip)
            manifest_crud.select_database("SG")
            json_sg_data = manifest_crud.read(filters=[("id", "in", [sg_id])])
            if json_sg_data:
                notes_tab_data = json_sg_data[-1]
            return notes_tab_data

        if event.subtype == "kTimeline":
            time_line_editor = hiero.ui.getTimelineEditor(hiero.ui.activeSequence())
            selection = time_line_editor.selection()
            if selection:
                selection = selection[-1]
                if isinstance(selection, hiero.core.VideoTrack):
                    seq = event.sender.sequence()
                    track_items = seq.trackItemsAt(hiero.ui.currentViewer().time())
                    video_track = hiero.ui.getTimelineEditor(
                        hiero.ui.activeSequence()
                    ).getSelection()[-1]
                    track_items = [
                        x for x in track_items if x.parent() == video_track
                    ]
                if isinstance(selection, hiero.core.TrackItem):
                    track_items = [selection]

        if not event.subtype:
            time_line_editor = hiero.ui.getTimelineEditor(hiero.ui.activeSequence())
            selection = time_line_editor.selection()
            if selection:
                selection = selection[-1]
                if isinstance(selection, hiero.core.VideoTrack):
                    seq = event.sender.sequence()
                    track_items = seq.trackItemsAt(hiero.ui.currentViewer().time())
                    video_track = hiero.ui.getTimelineEditor(
                        hiero.ui.activeSequence()
                    ).getSelection()[-1]
                    track_items = [
                        x for x in track_items if x.parent() == video_track
                    ]
                else:
                    seq = event.sender.sequence()
                    track_items = seq.trackItemsAt(hiero.ui.currentViewer().time())
            else:
                seq = event.sender.sequence()
                track_items = seq.trackItemsAt(hiero.ui.currentViewer().time())

        if track_items:
            clip = track_items[0].source()
            sg_id_tag = [x for x in clip.tags() if x.name() == "_sg_id"]
            sg_id = int(sg_id_tag[-1].note())

            manifest_crud.select_database("SG")
            json_sg_data = manifest_crud.read(filters=[("id", "in", [sg_id])])
            if json_sg_data:
                notes_tab_data = json_sg_data[-1]

    except Exception:
        pass

    return notes_tab_data

def hiero_timecode_to_frames(frame_rate, timecode_list):
    """Convert split SG timecode to Hiero timecode

    Args:
        frame_rate (float): frame rate to match timecode
        timecode_list (list): str split SG timecode

    Returns:
        (object): hiero.core.Timecode object
    """
    return hiero.core.Timecode.HMSFToFrames(
        frame_rate,
        False,
        int(timecode_list[0]),
        int(timecode_list[1]),
        int(timecode_list[2]),
        int(timecode_list[3]),
    )
