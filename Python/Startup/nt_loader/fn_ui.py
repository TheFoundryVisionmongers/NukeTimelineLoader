import json
import os
import datetime
import shutil

from qtpy.QtWidgets import (
    QTreeView,
    QStyledItemDelegate,
    QMenu,
    QAction,
    QAbstractItemView,
    QTabWidget,
    QComboBox,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QScrollArea,
    QFrame,
    QDialog,
    QCheckBox,
    QLineEdit,
    QMessageBox,
    QApplication,
    QSplitter,
    QActionGroup,
    QRadioButton,
    QButtonGroup,
    QSizePolicy,
)
from qtpy.QtGui import (
    QPixmap,
    QColor,
    QPalette,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QResizeEvent,
)
from qtpy.QtCore import Qt, Signal, QThreadPool, QRect, QSize, QMargins, QObject

from nt_loader.fn_model import LazyTreeModel, TreeItem
from nt_loader.fn_workers import (
    DataFetcher,
    WorkerSignals,
    SGDownloader,
    ImageSequenceCopier,
    TreeViewSignals,
    UPDATE_SIGNALS,
)
from nt_loader.fn_helpers import (
    split_camel_case,
    crop_edited_image,
    is_datetime_close,
)
from nt_loader.fn_hiero_func import (
    hiero_get_clip_sg_id,
    hiero_update_changed_items,
    hiero_add_files_to_bin,
    hiero_add_version_links_to_timeline,
    hiero_import_tags,
    hiero_capture_annotation,
    hiero_register_callbacks,
    hiero_unregister_callbacks,
    hiero_fire_callback
)
from nt_loader.fn_sg_func import (
    SgInstancePool,
    sgtimezone,
    sg_get_projects_for_combobox,
    sg_tree_search_entities,
    sg_get_version_thumb_filmstrip,
    sg_get_valid_statuses,
    sg_add_note,
    sg_add_reply,
    sg_update_status,
    setup_sg_tags,
    get_session_user
)
from nt_loader.fn_manifest_func import (
    create_manifest_entities,
    create_fn_version_link_entities,
    complete_fn_localization_strategy_entities,
    create_fn_localization_strategy_entities,
    create_fn_import_tasks_entity,
    update_fn_import_tasks_entity,
    check_fn_import_tasks_allowed,
    clear_fn_import_tasks,
)
from nt_loader.fn_crud import JsonCRUD

from nt_loader.fn_globals import (
    OPTIONS_BASE,
    OPTIONS_VISIBLE,
    CUSTOM_OPTIONS_FILE,
    SG_ENCODED_MEDIA_FIELDS,
    SG_MOVIE_FIELDS,
    SG_IMAGE_SEQUENCE_FIELDS,
    SG_MOVIE_PATH_FIELDS,
    NON_CONTEXT_ENTITIES,
    CONTEXT_ACTIONS,
    SG_NOTE_SUBJECT_TEMPLATE
)


class LoadingDialog(QDialog):
    """
    Loading dialog that is always ontop of QT stack
    """

    def __init__(self, text):
        """
        Args:
            text (str): text to load
        """

        super().__init__()
        self.text = text
        self.setWindowTitle("Loading")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint)
        self.setFixedSize(200, 100)
        self.layout = QVBoxLayout()
        self.label = QLabel(self.text)
        self.label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label)
        self.setLayout(self.layout)


class ShotgridLoaderWidget(QWidget):
    """Main Widget for loader application"""

    def __init__(
        self,
        sg,
        session_token,
        schema_map,
    ):
        """
        Args:
            sg (object): instantiated SGwrapper class provided by fn_sg_func.session_handler
            session_token (str): session token provided by fn_sg_func.session_handler
        """
        super().__init__()
        self.sg = sg
        self.session_token = session_token
        self.manifest_databases = {
            "SG": "sg_manifest.json",
            "FOUNDRY": "fn_manifest.json",
        }
        self.manifest_crud = JsonCRUD(self.manifest_databases)
        self.schema_map = schema_map
        self.view_option = [x for x in OPTIONS_BASE["Shotgrid View"] if "*" in x][
            -1
        ].strip("*")
        self.default_schema = self.schema_map[self.view_option]
        self.update_signals = UPDATE_SIGNALS

        self.localize_path = os.environ.get("SG_LOCALIZE_DIR", None)
        status_fields = sg.schema_field_read("Status")
        self.color_map = sg.find(
            "Status", filters=[], fields=list(status_fields.keys())
        )
        self.thread_pool = QThreadPool()
        self.html_error = '<span style="color: red;">{}</span>'
        self.selected_version_id = None
        self.icon_data = None
        self.entity_statuses = None
        self.options = None
        self.fn_base_entity = None
        self.note_selected = None
        self.setWindowTitle("NT Loader")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        tree_layout = QHBoxLayout()
        splitter = QSplitter()

        self.side_panel = QTabWidget()
        thumbnail_panel = ThumbFilmWidget(None, None, None)
        notes_panel = CommentReplyWidget(self.manifest_crud, None)
        options_base = OPTIONS_BASE
        if CUSTOM_OPTIONS_FILE:
            options_base = json.loads(CUSTOM_OPTIONS_FILE)
        self.options_panel = OptionsWidget(options_base)
        self.side_panel.addTab(thumbnail_panel, "Filmstrip")
        self.side_panel.addTab(notes_panel, "Notes")
        if OPTIONS_VISIBLE:
            self.side_panel.addTab(self.options_panel, "Options")
            self.options_panel.optionChanged.connect(
                self.update_foundry_base_entity_options
            )

        self.side_panel.setContentsMargins(0, 0, 0, 0)
        self.tree_panel = TreePanel(
            self.default_schema,
            NON_CONTEXT_ENTITIES,
            self.manifest_crud,
            self.color_map,
        )
        self.side_panel.currentChanged.connect(self.tree_panel.signals.tab_changed.emit)
        self.tree_panel.signals.note_selection.connect(self.update_notes_tab)
        self.tree_panel.signals.filmstrip_selection.connect(self.update_filmstrip_tab)
        self.tree_panel.signals.details_text.connect(self.update_details)
        self.tree_panel.signals.context_menu_action.connect(self.action_stub)

        splitter.insertWidget(0, self.tree_panel)
        splitter.insertWidget(1, self.side_panel)
        tree_layout.addWidget(splitter)
        layout.addLayout(tree_layout)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        detail_font_height = QFontMetrics(self.details_text.font()).lineSpacing()
        detail_line_height = detail_font_height * 5 + 10
        self.details_text.setMinimumHeight(detail_line_height)
        self.details_text.setMaximumHeight(detail_line_height)
        layout.addWidget(self.details_text)

        self.publish_changes_button = QPushButton("Publish changes to ShotGrid")
        self.publish_changes_button.clicked.connect(self.publish)
        layout.addWidget(self.publish_changes_button)

        self.update_signals.details_text.connect(self.update_details)

        self.setLayout(layout)

        if not self.localize_path:
            self.change_localize_path()

        self.manifest_crud.set_database_directory(self.localize_path)
        self.manifest_crud.select_database("FOUNDRY")
        self.fn_base_entity = self.manifest_crud.read(filters=[("id", "eq", 0)])
        if self.fn_base_entity:
            self.icon_data = self.fn_base_entity[-1]["icon_data"]

        if not self.icon_data:
            self.download_hiero_tags()

        if self.icon_data:
            self.setup_hiero_sg_tags()

        if not self.fn_base_entity:
            self.setup_foundry_base_entity()

        self.unregister_foundry_callbacks()
        self.register_foundry_callbacks()
        clear_fn_import_tasks(self.manifest_crud)

    def update_details(self, is_error, text):
        """Signal receiver from fn_workers.UPDATE_DETAILS

        Args:
            is_error (bool): True for error
            text (str): text to be displayed
        """
        if is_error:
            self.details_text.append(self.html_error.format(text))
        else:
            self.details_text.append("<span>{}</span>".format(text))

    def setup_foundry_base_entity(self):
        """Create Foundry manifest base entity at id 0"""
        self.manifest_crud.select_database("FOUNDRY")
        base_entity = self.manifest_crud.read(filters=[("id", "eq", 0)])
        if not base_entity:
            fn_base_entity = {
                "id": 0,
                "fn_type": "FoundryBaseEntity",
                "icon_data": self.icon_data,
                "color_map": self.color_map,
                "valid_statuses": {},
                "options": None,
            }

            schema_entities = [x for x in self.default_schema.keys()]
            # Apply standard end child entities
            schema_entities.append("Version")
            schema_entities.append("Note")

            # Entities without "sg_status_list"
            schema_entities.remove("root")
            schema_entities.remove("Project")

            if "Task" in schema_entities:
                schema_entities.remove("Task")

            valid_statuses = {}
            for entity in schema_entities:
                try:
                    valid_statuses.update(
                        {entity: sg_get_valid_statuses(self.sg, entity)}
                    )
                except Exception as e:
                    print(
                        "Non Critical Entity {} Does not have sg_status".format(entity)
                    )
                    continue

            fn_base_entity.update({"valid_statuses": valid_statuses})
            self.manifest_crud.upsert(fn_base_entity)

    def update_foundry_base_entity_options(self):
        """Update Foundry manifest base entity at id 0"""
        self.manifest_crud.select_database("FOUNDRY")
        base_entity = self.manifest_crud.read(filters=[("id", "eq", 0)])[-1]
        base_entity["options"] = self.options_panel.get_current_data()
        self.manifest_crud.update(0, base_entity)
        if self.options_panel.get_current_data()["Shotgrid View"] != self.view_option:
            self.tree_panel.schema = self.schema_map[
                self.options_panel.get_current_data()["Shotgrid View"]
            ]
            self.tree_panel.model.set_schema(self.tree_panel.schema)
            self.tree_panel.populate_entities()
            self.view_option = self.options_panel.get_current_data()["Shotgrid View"]

    def register_foundry_callbacks(self):
        """Register hiero callbacks which will provide event signals for UI operation"""
        hiero_register_callbacks(self.foundry_callback_fired)


    def unregister_foundry_callbacks(self):
        """Unregister above hiero callbacks"""
        hiero_unregister_callbacks(self.foundry_callback_fired)


    def foundry_callback_fired(self, event):
        """Receive the hiero event and translate to UI functionality.

        Args:
            event (object): hiero.core.Event object
        """
        notes_tab_data = hiero_fire_callback(self.manifest_crud, event)
        if notes_tab_data:
            self.update_notes_tab(notes_tab_data)

    def update_notes_tab(self, sg_data):
        """Receive signal from self.tree_panel which Clears tab and create widgets for notes

        Args:
            sg_data (dict): of SG manifest version entity to instantiate note widget
        """
        # Note: initially attempted signals based widgets but could not isolate a
        # slowdown (suspect rapid fire from hiero callbacks) so changed approach to instantiate widget with None and
        # manually clear tab and update.

        if sg_data["id"] != self.note_selected:
            self.manifest_crud.select_database("SG")
            manifest_sg_data = self.manifest_crud.read(
                filters=[("id", "eq", sg_data["id"])]
            )
            if manifest_sg_data:
                manifest_sg_data = manifest_sg_data[-1]
            else:
                manifest_sg_data = None
            tab = self.get_tab_by_name("Notes")
            if self.side_panel.currentWidget() == tab:
                self.clear_tab_by_name("Notes")
                tab_layout = tab.layout()
                notes_panel = CommentReplyWidget(self.manifest_crud, manifest_sg_data)
                self.note_selected = sg_data["id"]
                tab_layout.addWidget(notes_panel)
                tab_layout.setContentsMargins(0, 0, 0, 0)

    def update_filmstrip_tab(self, parent_item, data_list):
        """Receive signal from self.tree_panel which Clears tab and create widgets for notes

        Args:
            parent_item (QObject): parent TreeItem from treeview
            data_list (list): of paths and data required to instantiate filmscrubber widget
        """
        # Note: initially attempted signals based widgets but could not isolate a
        # slowdown (suspect rapid fire from hiero callbacks) so changed approach to instantiate widget with None and
        # manually clear tab and update.
        self.tab = self.get_tab_by_name("Filmstrip")
        if self.side_panel.currentWidget() == self.tab:
            self.clear_tab_by_name("Filmstrip")
            thumbnail, filmstrip, duration = data_list
            tab_layout = self.tab.layout()
            thumbnail_panel = ThumbFilmWidget(filmstrip, thumbnail, duration)
            tab_layout.addWidget(thumbnail_panel)
            tab_layout.addStretch()

    def get_tab_by_name(self, tab_name):
        """Retrieve a tab by its str name"""
        for i in range(self.side_panel.count()):
            if self.side_panel.tabText(i) == tab_name:
                tab = self.side_panel.widget(i)
                return tab

    def clear_tab_by_name(self, tab_name):
        """Clear a tabs widgets and layouts by its str name"""
        tab = self.get_tab_by_name(tab_name)
        layout = tab.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
                break

    def add_files_to_hiero(self):
        """Complete localization strategy entities and trigger hiero functions to import files to hiero"""
        fn_import_task = self.manifest_crud.read(filters=[("state", "eq", "new")])[-1]
        fn_import_ids = fn_import_task["fn_ids_import"]
        complete_fn_localization_strategy_entities(
            self.manifest_crud, self.localize_ids
        )
        self.localize_ids = []

        self.options = self.options_panel.get_current_data()
        self.update_foundry_base_entity_options()
        try:
            hiero_add_files_to_bin(
                self.manifest_crud,
                fn_import_ids,
                self.color_map,
                self.sg,
            )
        except Exception as e:
            self.details_text.append(
                self.html_error.format(
                    "Exception caught in adding files to Hiero bin !\n{}".format(e)
                )
            )
            fn_import_task["state"] = "fail"
            update_fn_import_tasks_entity(
                self.manifest_crud, fn_import_task["id"], fn_import_task
            )
            return

        self.details_text.append("All files added!")
        self.details_text.append("Please wait adding clips to timeline...")

        try:
            hiero_add_version_links_to_timeline(self.manifest_crud, fn_import_ids)
        except Exception as e:
            self.details_text.append(
                self.html_error.format(
                    "Exception caught in adding files to Hiero Timeline !\n{}".format(e)
                )
            )

            fn_import_task["state"] = "fail"
            update_fn_import_tasks_entity(
                self.manifest_crud, fn_import_task["id"], fn_import_task
            )
            return

        fn_import_task["stage"] = "timeline_import"
        fn_import_task["state"] = "comp"
        update_fn_import_tasks_entity(
            self.manifest_crud, fn_import_task["id"], fn_import_task
        )

    def change_localize_path(self):
        """Create a dialog to change the localize path"""
        new_path = QFileDialog.getExistingDirectory(
            self, "Select Localization Directory"
        )
        if new_path:
            self.localize_path = os.path.normpath(new_path)
            self.details_text.append(
                f"Localization path changed to: {self.localize_path}"
            )
            # Automatically setup SG status tags in new localize directory
            self.setup_hiero_sg_tags()
            os.environ["SG_LOCALIZE_DIR"] = new_path

    def download_hiero_tags(self):
        """download tags if none found in fn_base_entity"""
        self.icon_data = setup_sg_tags(self.sg, self.session_token, self.localize_path)
        self.details_text.append("Downloaded SG Icons")

    def setup_hiero_sg_tags(self):
        """Trigger hieor and SG functions to setup status tags in hiero project"""
        if not self.icon_data:
            self.download_hiero_tags()
        hiero_import_tags(self.icon_data)
        self.details_text.append("Added tags to project")

    def action_stub(self, entity_ids, action_text):
        """Runs the required functions for context actions denoted above based on
        the string of the action and current selection/s
        Args:
            entity_ids (list): list of SG manifest version entity ids
            action_text (str): signal from self.tree_panel contex menu action.
        """
        # __CUSTOMIZE__ These can be edited to suite the required operations of your studio
        # see fn_ui.ShotgridLoader.action_stub for functionality assignment
        localize_map = {
            "Localize SG encoded media/s": SG_ENCODED_MEDIA_FIELDS,
            "Localize image sequences/s": SG_IMAGE_SEQUENCE_FIELDS,
            "Localize movie media/s": SG_MOVIE_FIELDS,
            "Direct link to image sequences/s": SG_IMAGE_SEQUENCE_FIELDS,
            "Direct link to movie media/s": SG_MOVIE_PATH_FIELDS,
        }

        if action_text in [
            "Localize SG encoded media/s",
        ]:
            if not check_fn_import_tasks_allowed(self.manifest_crud):
                self.details_text.append(
                    self.html_error.format("Previous import in progress!")
                )
                return

            fn_ids_for_import = create_fn_version_link_entities(
                self.manifest_crud, entity_ids
            )

            self.localize_ids = create_fn_localization_strategy_entities(
                self.manifest_crud, entity_ids, localize_map[action_text]
            )
            if self.localize_ids:
                create_fn_import_tasks_entity(self.manifest_crud, fn_ids_for_import)
                self.downloader = SGDownloader(
                    self.manifest_crud, self.localize_ids, SgInstancePool(maxsize=5)
                )
                self.downloader.signals.done.connect(self.add_files_to_hiero)
                self.downloader.start_downloads()
            else:
                create_fn_import_tasks_entity(self.manifest_crud, fn_ids_for_import)
                self.add_files_to_hiero()

        # __CUSTOMIZE__ This copies media and could be re-enabled for cross site usage
        # see also fn_globals.py CONTEXT_ACTIONS
        # if action_text in [
        #     "Localize image sequences/s",
        #     "Localize movie media/s",
        # ]:
        #     if self.ids_for_bin:
        #         self.details_text.append(
        #             self.html_error.format("Previous import in progress!")
        #         )
        #         return
        #     self.ids_for_bin = create_fn_version_link_entities(
        #         self.manifest_crud, entity_ids
        #     )
        #     self.localize_ids = create_fn_localization_strategy_entities(
        #         self.manifest_crud, entity_ids, localize_map[action_text]
        #     )
        #     if self.localize_ids:
        #         self.copier = ImageSequenceCopier(self.manifest_crud, self.localize_ids)
        #         self.copier.signals.done.connect(self.add_files_to_bin)
        #         self.copier.start_copy()
        #     else:
        #         self.add_files_to_bin()

        if action_text in [
            "Direct link to image sequences/s",
            "Direct link to movie media/s",
        ]:
            if not check_fn_import_tasks_allowed(self.manifest_crud):
                self.details_text.append(
                    self.html_error.format("Previous import in progress!")
                )
                return

            fn_ids_for_import = create_fn_version_link_entities(
                self.manifest_crud, entity_ids
            )

            self.localize_ids = create_fn_localization_strategy_entities(
                self.manifest_crud, entity_ids, localize_map[action_text], direct=True
            )
            if self.localize_ids:
                create_fn_import_tasks_entity(self.manifest_crud, fn_ids_for_import)
                self.add_files_to_hiero()

        if action_text in [
            "Sync SG notes",
        ]:
            self.details_text.append("Synchronizing Manifests Notes")

        if action_text in [
            "Change Localize Directory",
        ]:
            self.change_localize_path()

        if action_text in ["Clear Edits", "Clear SG Manifests"]:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("Warning")
            if action_text == "Clear SG Manifests":
                msg_box.setText(
                    f"Warning ! you are about to {action_text}. This will not remove any existing edits but will remove any localized SG manifest content.\nThis can be used if there is some inconsistency in performance.\nDO NOT USE IN SYNC SESSION\n\nClick Yes to proceed"
                )
            if action_text == "Clear Edits":
                msg_box.setText(
                    f"Warning ! you are about to {action_text}.\nThis will remove any unpublished user created edits!\n\nClick Yes to proceed"
                )
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg_box.setDefaultButton(QMessageBox.No)
            result = msg_box.exec_()

            if result == QMessageBox.Yes:
                # backup manifests
                backup_directory = os.path.join(
                    self.localize_path,
                    "manifest_backup_{}".format(
                        datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    ),
                )
                self.details_text.append(
                    "Backing up manifests to {}".format(backup_directory)
                )
                os.makedirs(backup_directory, exist_ok=True)
                manifest_files = [
                    os.path.join(self.localize_path, "fn_manifest.json"),
                    os.path.join(self.localize_path, "sg_manifest.json"),
                ]
                [shutil.copy2(x, backup_directory) for x in manifest_files]
                if action_text == "Clear SG Manifests":
                    self.manifest_crud.clear_database("SG")
                    self.details_text.append("SG Manifest cleared")
                if action_text == "Clear Edits":
                    self.manifest_crud.select_database("FOUNDRY")
                    edits = self.manifest_crud.read(
                        filters=[
                            (
                                "fn_type",
                                "in",
                                ["NewNote", "StatusChange", "NoteReply"],
                            )
                        ]
                    )
                    for edit in edits:
                        self.manifest_crud.delete(edit["id"])
                    self.details_text.append("Edits cleared")

    def publish(self):
        """Popup a dialog showing the edits to version status and notes. On submit bulk upload to SG"""
        change_report = ChangeReportSubmit(self.manifest_crud, self.sg)
        change_report.exec_()


class FilterSearchWidget(QWidget):
    """
    Widget for filtering and advanced search features used in conjunction with tree model filter
    """

    def __init__(self, signals, parent=None):
        """
        Initialise the filtering widget. Signals connected to TreePanel for search reset
        Args:
            signals:
            parent:
        """
        super().__init__(parent)
        self.init_ui()
        self.search_mode = "filter"
        self.signals = signals

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        self.options_button = QPushButton()
        self.options_button.setIcon(
            self.style().standardIcon(self.style().SP_FileDialogContentsView)
        )
        self.options_button.setStyleSheet("border:none")
        self.options_button.setFixedSize(QSize(30, 30))

        self.options_button.clicked.connect(self.show_context_menu)

        # search fields container
        self.search_widget = QWidget()
        self.search_layout = QHBoxLayout(self.search_widget)
        self.search_layout.setContentsMargins(0, 0, 0, 0)
        self.search_layout.setSpacing(5)

        # Live filter mode
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter...")
        self.filter_input.setStyleSheet("border:none")

        # Basic Search mode
        self.project_combo = QComboBox()
        self.project_combo.setStyleSheet("border:none")
        self.project_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.project_combo.hide()

        self.entity_combo = QComboBox()
        self.entity_combo.setStyleSheet("border:none")
        self.entity_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.entity_combo.hide()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")
        self.search_input.setStyleSheet("border:none")
        self.search_input.hide()

        # Advanced search mode
        self.advanced_search_input = QLineEdit()
        self.advanced_search_input.setPlaceholderText(
            "Formatted Search IE: project|entity|search&project|entity|search&..."
        )
        self.advanced_search_input.setStyleSheet("border:none")
        self.advanced_search_input.hide()

        self.search_button = QPushButton()
        self.search_button.setStyleSheet("border:none")
        self.search_button.setIcon(
            self.style().standardIcon(self.style().SP_ArrowRight)
        )
        self.search_button.setFixedSize(QSize(30, 30))
        self.search_button.hide()

        palette = self.search_input.palette()
        self.container.setStyleSheet(
            f"border-radius: 10px;background-color: {palette.base().color().name()}"
        )

        self.search_layout.addWidget(self.filter_input)
        self.search_layout.addWidget(self.project_combo)
        self.search_layout.addWidget(self.entity_combo)
        self.search_layout.addWidget(self.search_input)
        self.search_layout.addWidget(self.advanced_search_input)
        self.search_layout.addWidget(self.search_button)

        container_layout.addWidget(self.options_button)
        container_layout.addWidget(self.search_widget)
        main_layout.addWidget(self.container)

    def show_context_menu(self):
        """
        Context menu for filter search bar
        """
        menu = QMenu(self)

        # radio buttons
        filter_action = QAction("Filter", menu)
        filter_action.setCheckable(True)
        filter_action.setChecked(self.search_mode == "filter")

        search_action = QAction("Search", menu)
        search_action.setCheckable(True)
        search_action.setChecked(self.search_mode == "search")

        advanced_search_action = QAction("Advanced Search", menu)
        advanced_search_action.setCheckable(True)
        advanced_search_action.setChecked(self.search_mode == "advanced_search")

        reset_action = QAction("Reset", menu)
        copy_action = QAction("Copy Search Stack", menu)

        action_group = QActionGroup(menu)
        action_group.addAction(filter_action)
        action_group.addAction(search_action)
        action_group.addAction(advanced_search_action)
        action_group.setExclusive(True)

        menu.addAction(filter_action)
        menu.addAction(search_action)
        menu.addAction(advanced_search_action)
        menu.addSeparator()
        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction(reset_action)

        filter_action.triggered.connect(lambda: self.switch_mode("filter"))
        search_action.triggered.connect(lambda: self.switch_mode("search"))
        advanced_search_action.triggered.connect(
            lambda: self.switch_mode("advanced_search")
        )
        reset_action.triggered.connect(lambda: self.signals.search_reset.emit(True))
        copy_action.triggered.connect(lambda: self.signals.copy_search.emit(True))
        menu.exec_(
            self.options_button.mapToGlobal(self.options_button.rect().bottomLeft())
        )

    def switch_mode(self, mode):
        """
        Actions triggered by context menu depending on selection
        """
        self.search_mode = mode
        if mode == "filter":
            self.filter_input.show()
            self.project_combo.hide()
            self.entity_combo.hide()
            self.search_input.hide()
            self.advanced_search_input.hide()
            self.search_button.hide()
        if mode == "search":
            self.filter_input.hide()
            self.filter_input.setText("")
            self.advanced_search_input.hide()
            self.search_input.show()
            self.project_combo.show()
            self.entity_combo.show()
            self.search_button.show()
        if mode == "advanced_search":
            self.filter_input.hide()
            self.filter_input.setText("")
            self.project_combo.hide()
            self.entity_combo.hide()
            self.search_input.hide()
            self.advanced_search_input.show()
            self.search_button.show()


class TreePanel(QWidget):
    """Panel to show search bar and tree model based on selected schema"""

    def __init__(self, schema, non_context_entities, manifest_crud, color_map):
        """
        Args:
            schema (dict): schema to drive fn_model.LazyTreeModel
            non_context_entities (list): of TreeItem.node_types which do not have right click menu options
            manifest_crud (object): manifest crud object
            color_map (dict): color map derived from Foundry manifest base entity
        """
        super(TreePanel, self).__init__()
        self.signals = TreeViewSignals()
        self.sg_instance_pool = SgInstancePool(maxsize=7)
        self.thread_pool = QThreadPool()
        self.color_map = color_map
        self.schema = schema
        self.non_context_entities = non_context_entities
        self.manifest_crud = manifest_crud
        self.retrieve_filmstrip = True
        self.search_stack = []
        self.search_parameters = []
        self.init_ui()
        self.load_projects()

    def init_ui(self):
        # Layouts
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_search = FilterSearchWidget(self.signals)
        self.filter_search.search_button.clicked.connect(self.on_search_clicked)
        self.populate_entities()
        self.filter_search.filter_input.textChanged.connect(self.filter_tree)

        # Add controls to main layout
        main_layout.addWidget(self.filter_search)

        # Tree View
        self.tree_view = QTreeView()
        self.model = LazyTreeModel(
            schema=self.schema,
            non_context_items=self.non_context_entities,
            instance_pool=self.sg_instance_pool,
            manifest_crud=self.manifest_crud,
        )
        self.tree_view.setModel(self.model)
        main_layout.addWidget(self.tree_view)
        sort_layout = QHBoxLayout()
        sort_label = QLabel("Sort by")
        sort_layout.addWidget(sort_label)
        self.radio_group = QButtonGroup()
        name_sort = QRadioButton("Name")
        date_sort = QRadioButton("Date")
        self.radio_group.addButton(name_sort)
        self.radio_group.addButton(date_sort)
        sort_layout.addWidget(name_sort)
        sort_layout.addWidget(date_sort)
        self.radio_group.setExclusive(True)
        name_sort.setChecked(True)
        self.radio_group.buttonClicked.connect(self.sort_tree)

        main_layout.addLayout(sort_layout)
        self.tree_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        color_delegate = StatusColorDelegate(self.color_map)
        self.tree_view.setItemDelegate(color_delegate)
        self.tree_view.setSelectionMode(QTreeView.ExtendedSelection)
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_context_menu)
        self.tree_view.selectionModel().selectionChanged.connect(self.send_tab_details)
        self.tree_view.expanded.connect(self.resize_content)
        self.signals.tab_changed.connect(self.tab_selected)
        self.signals.search_reset.connect(self.on_reset_clicked)
        self.signals.copy_search.connect(self.on_copy_search)

        self.setLayout(main_layout)

    def resize_content(self):
        """Function repeatedly called to provide a better viewable treeview when long naming"""
        for i in range(0, self.model.columnCount()):
            self.tree_view.resizeColumnToContents(i)

    def load_projects(self):
        # Fetch projects in a separate thread
        worker = DataFetcher(
            fetch_func=sg_get_projects_for_combobox,
            parent_item=None,
            sg_instance_pool=self.sg_instance_pool,
            signals=WorkerSignals(),
        )
        worker.signals.data_fetched.connect(self.on_projects_fetched)
        self.thread_pool.start(worker)

    def populate_entities(self):
        # Populate entity types from schema (excluding 'root' and 'Project')
        self.filter_search.entity_combo.clear()
        entity_types = list(
            x for x in self.schema.keys() if self.schema[x].get("_searchable", True)
        )
        entity_types.append("Version")
        entity_types.remove("root")
        entity_types.remove("Project")
        self.filter_search.entity_combo.addItems(entity_types)

    def on_projects_fetched(self, _, projects):
        # Populate project combo box
        project_names = [project["name"] for project in projects]
        self.filter_search.project_combo.addItems(project_names)

    def on_search_clicked(self):
        self.model.search_mode = True
        if self.filter_search.search_mode == "search":
            selected_project = self.filter_search.project_combo.currentText()
            entity_type = self.filter_search.entity_combo.currentText()
            search_term = self.filter_search.search_input.text()
            self.search_parameters.append(
                "{}|{}|{}".format(selected_project, entity_type, search_term)
            )
            # Fetch search results
            worker = DataFetcher(
                fetch_func=sg_tree_search_entities,
                parent_item=None,
                sg_instance_pool=self.sg_instance_pool,
                signals=WorkerSignals(),
                project_name=selected_project,
                entity_type=entity_type,
                search_term=search_term,
            )
            worker.signals.data_fetched.connect(self.on_search_results)
            self.thread_pool.start(worker)

        if self.filter_search.search_mode == "advanced_search":
            search_term = self.filter_search.advanced_search_input.text()
            searches = search_term.split("&")
            for search in searches:
                if len(search.split("|")) != 3:
                    UPDATE_SIGNALS.details_text.emit(
                        True, "Error in formating of search {}".format(search)
                    )
                    return
                else:
                    project = search.split("|")[0]
                    entity_type = search.split("|")[1]
                    search_term = search.split("|")[2]
                    self.search_parameters.append(
                        "{}|{}|{}".format(project, entity_type, search_term)
                    )
                    # Fetch search results
                    worker = DataFetcher(
                        fetch_func=sg_tree_search_entities,
                        parent_item=None,
                        sg_instance_pool=self.sg_instance_pool,
                        signals=WorkerSignals(),
                        project_name=project,
                        entity_type=entity_type,
                        search_term=search_term,
                    )
                    worker.signals.data_fetched.connect(self.on_search_results)
                    self.thread_pool.start(worker)

    def on_search_results(self, _, results):
        if not self.search_stack:

            # Build new root item
            self.model.beginResetModel()
            self.model.root_item = TreeItem(
                name="Search Results", node_type="root", schema=self.model.schema
            )
            self.model.root_item.loaded = True  # Prevent fetching data for root item
            self.search_stack.append(1)
            self.model.root_item.append_child(
                TreeItem(
                    name="Search - {}".format(len(self.search_stack)),
                    node_type="Search",
                    schema={},
                )
            )
            self.model.endResetModel()
        else:
            self.search_stack.append(len(self.model.root_item.children))

        # Add search results as children of the root item
        if results:
            self.model.beginInsertRows(
                self.model.index_from_item(self.model.root_item.children[-1]),
                self.search_stack[-1],
                self.search_stack[-1] + 1,
            )
            self.model.root_item.append_child(
                TreeItem(
                    name="Search - {}".format(len(self.search_stack)),
                    node_type="Search",
                    schema={},
                )
            )
            self.model.endInsertRows()
            start_item = self.model.root_item.children[-1]
            self.model.beginInsertRows(
                self.model.index_from_item(start_item),
                0,
                len(results),
            )
            # Ensure search mode is True
            for item_info in results:
                name = item_info["name"]
                node_type = item_info["node_type"]
                item_status = item_info.get("item_status")
                data = item_info.get("data")
                child_item = TreeItem(
                    name=name,
                    parent=start_item,
                    node_type=node_type,
                    item_status=item_status,
                    data=data,
                    schema=self.model.schema,
                )

                start_item.append_child(child_item)

            start_item.loaded = True
            self.model.endInsertRows()
            self.tree_view.expand(self.model.index_from_item(start_item))
            self.resize_content()
        else:
            UPDATE_SIGNALS.details_text.emit(False, "No matching search results found.")

    def on_reset_clicked(self):
        # Reset the model to the default schema
        self.model.search_mode = False  # Set search mode to False
        self.search_stack = []
        self.search_parameters = []
        self.model.reset_data()

    def on_copy_search(self):
        if not self.search_parameters:
            UPDATE_SIGNALS.details_text.emit(True, "No search stack in tree cache")
        else:
            UPDATE_SIGNALS.details_text.emit(
                False,
                "Advanced Search String Copied to clipboard :\n{}".format(
                    "&".join(self.search_parameters)
                ),
            )
            clipboard = QApplication.clipboard()
            clipboard.setText("&".join(self.search_parameters))

    def show_context_menu(self, position):
        """
        Main context menu for tool uses the selection to fire actions through action stub in treePanel and ShotgridLoader
        widget
        """
        menu = QMenu()

        for action_text in CONTEXT_ACTIONS:  # from fn_globals.CONTEXT_ACTIONS
            if action_text == "---":
                menu.addSeparator()
            else:
                action = QAction(action_text, self)
                # Pyside2 has differing syntax to Qt. checked needs to be passed
                # as None for dynamic signal lambda assignment
                action.triggered.connect(
                    lambda checked=None, text=action_text: self.action_stub(text)
                )
                menu.addAction(action)

        menu.exec_(self.tree_view.viewport().mapToGlobal(position))

    def action_stub(self, action_text):
        """
        First phase of action stub . depending on the action fired will sync manifests of the selection followed by firing
        ShotgridLoader.action_stub
        """
        selected_items = [
            self.model.itemFromIndex(index)
            for index in self.tree_view.selectedIndexes()
            if index.column() == 0
        ]
        self.selected_ids = [x.data["id"] for x in selected_items]
        self.action_text = action_text

        # __CUSTOMIZE__ These can be edited to suit the required operations of your studio
        # see fn_ui.ShotgridLoader.action_stub for functionality assignment
        # Below actions do not need manifest sync
        if action_text in [
            "Change Localize Directory",
            "Clear Edits",
            "Clear SG Manifests",
        ]:
            self.signals.context_menu_action.emit(self.selected_ids, self.action_text)
            return

        # Right click actions require SG manifest entities to be up to date below creates or updates these
        for item in selected_items:
            self.manifest_crud.select_database("SG")
            worker = DataFetcher(
                fetch_func=create_manifest_entities,
                parent_item=item,
                sg_instance_pool=self.sg_instance_pool,
                signals=WorkerSignals(),
                manifest_crud=self.manifest_crud,
            )
            worker.signals.finished.connect(self.sg_manifest_done)
            self.thread_pool.start(worker)

    def tab_selected(self, index):
        """Send signal to assess tab contents on tab change"""
        selected_items = [
            self.model.itemFromIndex(i)
            for i in self.tree_view.selectedIndexes()
            if i.column() == 0
        ]
        if not selected_items:
            return
        if index == 0:
            self.retrieve_filmstrip = True
            self.send_tab_details(0, 0, parent_item=selected_items[-1])
        if index == 1:
            self.retrieve_filmstrip = False
            self.send_tab_details(0, 0, parent_item=selected_items[-1])

    def send_tab_details(self, selected, deselected, parent_item=None):
        """Send signal with required data to update notes or filmscrubber tab"""
        item = None
        if selected and deselected != 0:
            indexes = selected.indexes()
            if indexes:
                item = self.model.itemFromIndex(indexes[0])
        if parent_item:
            item = parent_item

        if not item:
            return

        if item.node_type == "Version":
            if self.retrieve_filmstrip:
                UPDATE_SIGNALS.details_text.emit(
                    False, "Retrieving filmstrip for - {}".format(item.name)
                )
                worker = DataFetcher(
                    fetch_func=sg_get_version_thumb_filmstrip,
                    parent_item=item,
                    sg_instance_pool=self.sg_instance_pool,
                    signals=WorkerSignals(),
                    manifest_crud=self.manifest_crud,
                )
                worker.signals.data_fetched.connect(self.filmstrip_received)
                self.thread_pool.start(worker)

        if not self.retrieve_filmstrip:
            self.signals.note_selection.emit(item.data)

    def filmstrip_received(self, parent_item, data):
        """
        Receives data from threaded filmstrip download and fires for tab update
        """
        self.signals.filmstrip_selection.emit(parent_item, data)

    def sg_manifest_done(self, _):
        """Signal to signify manifest entity has been created from right click context menu action"""
        self.signals.context_menu_action.emit(self.selected_ids, self.action_text)
        self.selected_ids = None
        self.action_text = None

    def filter_tree(self):
        filter_text = self.filter_search.filter_input.text()
        self.model.filter(filter_text)

    def sort_tree(self, button):
        self.model.sorting = button.text().lower()
        self.model.sort_by(self.model.root_item)
        self.model.reset_data()


class StatusColorDelegate(QStyledItemDelegate):
    """
    Apply specific colors and styling to a cell by overriding the widget base class
    """

    def __init__(self, color_map, parent=None):
        super().__init__(parent)
        self.color_map = color_map

    def paint(self, painter, option, index):
        """
        Customized/Overridden class method to apply stylization
        """

        cell_status = index.data(Qt.DisplayRole)

        for status in self.color_map:
            # Check if the cell value is from the SG status list and apply same
            # color
            if status["code"] == cell_status:
                if status["bg_color"]:
                    color1, color2, color3 = (
                        int(x) for x in status["bg_color"].split(",")
                    )
                    bg_color = QColor(color1, color2, color3)
                    painter.fillRect(option.rect, bg_color)
                    text_color = self.get_contrasting_text_color(bg_color)
                    option.palette.setColor(QPalette.Text, text_color)
            # Check if the cell values are for caching and apply color
            if cell_status in ["X", "<"]:
                # Red
                bg_color = QColor(255, 0, 0)
                painter.fillRect(option.rect, bg_color)
                text_color = self.get_contrasting_text_color(bg_color)
                option.palette.setColor(QPalette.Text, text_color)
            if cell_status == "✓":
                # Green
                bg_color = QColor(0, 255, 0)
                painter.fillRect(option.rect, bg_color)
                text_color = self.get_contrasting_text_color(bg_color)
                option.palette.setColor(QPalette.Text, text_color)
            if cell_status == "=":
                # Green
                bg_color = QColor(0, 255, 0)
                painter.fillRect(option.rect, bg_color)
                text_color = self.get_contrasting_text_color(bg_color)
                option.palette.setColor(QPalette.Text, text_color)
            if cell_status == "Direct":
                # Blue
                bg_color = QColor(0, 0, 255)
                painter.fillRect(option.rect, bg_color)
                text_color = self.get_contrasting_text_color(bg_color)
                option.palette.setColor(QPalette.Text, text_color)
            if isinstance(cell_status, int):
                if cell_status > 0:
                    # Yellow Edit Color
                    bg_color = QColor(255, 255, 0)
                    painter.fillRect(option.rect, bg_color)
                    text_color = self.get_contrasting_text_color(bg_color)
                    option.palette.setColor(QPalette.Text, text_color)

        # apply the color to the cell
        QStyledItemDelegate.paint(self, painter, option, index)

    def get_contrasting_text_color(self, bg_color):
        """
        For UI readability assess the color of the cell vs text and return
        contrasting text color

        Args:
            bg_color (QColor): color of the cell

        Returns:
            QColor: contrasting text color for cell contents
        """
        brightness = (
            299 * bg_color.red() + 587 * bg_color.green() + 114 * bg_color.blue() / 1000
        )
        return QColor(Qt.black) if brightness > 127 else QColor(Qt.white)


class BubbleLabel(QLabel):
    """Custom label to represent chat like speech bubbles"""

    def __init__(self, text, is_sent=False, parent=None):
        """Creates SMS like Qpainted label for notes display

        Args:
            text (str): text to be inside speech bubble
            is_sent (bool, optional): Denotes which side the speech bubbles tick is. Defaults to False.
            parent (_type_, optional): Defaults to None.
        """
        # TODO implement SG like markdown/up for text
        super().__init__(text, parent)
        self.is_sent = is_sent
        self.bubble_color = QColor("#2a2a2a")
        self.text_color = Qt.white
        self.margin = 5  # Margin inside the bubble

    def paintEvent(self, event):
        """Custom paint override

        Args:
            event (object): QT event trigger
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        bubble_rect = QRect(rect)
        tail_width = 10
        tail_height = 10

        # Adjust bubble rect based on whether it's sent or received
        if self.is_sent:
            bubble_rect.setRight(rect.right() - tail_width)
        else:
            bubble_rect.setLeft(tail_width)

        # Create bubble path
        path = QPainterPath()
        radius = 10
        path.addRoundedRect(bubble_rect, radius, radius)

        # Add the "tail" to the bubble
        if self.is_sent:
            path.moveTo(
                bubble_rect.right() + 1, bubble_rect.center().y() - tail_height // 2
            )
            path.lineTo(rect.right(), bubble_rect.center().y())
            path.lineTo(
                bubble_rect.right() + 1, bubble_rect.center().y() + tail_height // 2
            )
        else:
            path.moveTo(bubble_rect.left(), bubble_rect.center().y() - tail_height // 2)
            path.lineTo(rect.left(), bubble_rect.center().y())
            path.lineTo(bubble_rect.left(), bubble_rect.center().y() + tail_height // 2)

        # Draw bubble
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.bubble_color)
        painter.drawPath(path)

        # Draw text
        painter.setPen(self.text_color)
        text_rect = bubble_rect.marginsRemoved(
            QMargins(self.margin, self.margin, self.margin, self.margin)
        )
        painter.drawText(text_rect, Qt.AlignLeft | Qt.TextWordWrap, self.text())

    def sizeHint(self):
        """Qt override to ensure text is encapsulated in bubble"""
        width = (
            self.fontMetrics()
            .boundingRect(self.rect(), Qt.TextWordWrap, self.text())
            .width()
        )
        return QSize(
            width + 2 * self.margin + 20, 0
        )  # Add extra width for margins and tail


class FilmstripScrubber(QWidget):
    """Widget to display Thumbnail or Filmstrip with click scrubbing"""

    timeChanged = Signal(float)

    def __init__(self, filmstrip_path, alternate_image_path, duration):
        """
        Drives the filmstrip tab for hover and thumbnail display
        Args:
            filmstrip_path (str): path to downloaded filmstrip
            alternate_image_path (str): path to thumbnail when filmstrip scrubbing not in use
            duration (float): duration of version video content . drives how to break up filmstrip image
        """
        super().__init__()
        self.filmstrip = QPixmap(filmstrip_path)
        self.alternate_image = QPixmap(alternate_image_path)
        self.frame_width = 240.0
        self.num_frames = self.filmstrip.width() / self.frame_width
        self.duration = duration
        self.frame_rate = self.num_frames / self.duration

        self.current_frame = 0
        self.is_hovering = False

        self.setMouseTracking(True)

        target_width, target_height = 480, 270
        original_width = self.alternate_image.width()
        original_height = self.alternate_image.height()

        aspect_ratio = original_width / original_height
        target_aspect_ratio = target_width / target_height

        if aspect_ratio > target_aspect_ratio:
            new_width = target_width
            new_height = int(new_width / aspect_ratio)
        else:
            new_height = target_height
            new_width = int(new_height * aspect_ratio)

        self.alternate_image = self.alternate_image.scaled(
            new_width, new_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setFixedSize(new_width, new_height)
        self.image_label = QLabel(self)
        self.image_label.setGeometry(0, 0, self.width(), self.height())

        self.update_display()

    def update_display(self):
        """Updates display depending on context"""
        if self.is_hovering:
            self.update_frame(self.current_frame)
        else:
            self.image_label.setPixmap(self.alternate_image)

    def update_frame(self, frame):
        """When scrubbing jump to frame

        Args:
            frame (int): frame number to display
        """
        self.current_frame = frame
        x = frame * self.frame_width
        frame_rect = QRect(x, 0, self.frame_width, self.filmstrip.height())
        frame_pixmap = self.filmstrip.copy(frame_rect)
        scaled_pixmap = frame_pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)

    def enterEvent(self, event):
        """Mouse over event override

        Args:
            event (object): Qt event trigger
        """
        self.is_hovering = True
        self.update_display()

    def leaveEvent(self, event):
        """Mouse leave event override

        Args:
            event (object): Qt event trigger
        """
        self.is_hovering = False
        self.update_display()
        self.timeChanged.emit(-1)  # Signal that we're no longer hovering

    def mouseMoveEvent(self, event):
        """Mouse movie inside widget event override

        Args:
            event (object): Qt event trigger
        """
        if self.is_hovering:
            x = event.x()
            frame = int((x / self.width()) * self.num_frames)
            self.update_frame(min(frame, self.num_frames - 1))
            self.timeChanged.emit(self.get_current_time())

    def get_current_time(self):
        """Get the current frame and approximate the time

        Returns:
            float: time in seconds
        """
        return self.current_frame / self.frame_rate


class ThumbFilmWidget(QWidget):
    """Widget to display filmstrip tab and FilmStripScrubber if applicable"""

    def __init__(self, filmstrip_path, alternate_image_path, duration):
        """
        Args:
            filmstrip_path (str): path to filmstrip to be handed downstream to FilmStripScrubber
            alternate_image_path (str): path to thumbnail to be handed downstream to FilmStripScrubber
            duration (float): duration of version video content to be handed downstream to FilmStripScrubber
        """
        super().__init__()
        self.filmstrip_path = filmstrip_path
        self.alternate_image_path = alternate_image_path
        self.duration = duration
        self.widget_layout = None
        self.init_ui()

    def init_ui(self):
        """Initialize the layout of the widget. But if None in args display selection requirements"""
        if self.widget_layout:
            self.clear_layout(self.widget_layout)
        self.widget_layout = QVBoxLayout()
        self.scrub_info = QLabel()
        if not all([self.filmstrip_path, self.alternate_image_path, self.duration]):
            self.scrub_info.setText("Select Single Version in tree view for filmstrip")
            self.widget_layout.addWidget(self.scrub_info)
        else:
            self.scrub_info.setText("Click and drag thumbnail to scrub frames")
            self.widget_layout.addWidget(self.scrub_info)
            self.scrubber = FilmstripScrubber(
                self.filmstrip_path, self.alternate_image_path, self.duration
            )
            self.widget_layout.addWidget(self.scrubber)
            self.time_label = QLabel()
            self.widget_layout.addWidget(self.time_label)
            # Connect the timeChanged signal to update_time_label
            self.scrubber.timeChanged.connect(self.update_time_label)
        self.setMinimumSize(480, 270)
        self.setLayout(self.widget_layout)

    def clear_layout(self, layout):
        """
        Clears the layout

        Args:
            layout (QWidget): Layout to clear
        """
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def update_time_label(self, time):
        """Display senconds in QLabel

        Args:
            time (float): seconds recieved by FilmStripScrubber
        """
        if time >= 0:
            self.time_label.setText(f"Time: {time:.2f}s")


class ImageDialog(QDialog):
    """Dialog to Display full size image of annotations and attached images"""

    def __init__(self, image_path, parent=None):
        """
        Pops a resizable dialog when clicking on a annotation image in the notes tab
        Args:
            image_path (str): path to image to display
        """
        super().__init__(parent)
        self.image_path = image_path
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Full Image")
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.image_label = QLabel()
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.image_label)

        self.original_pixmap = QPixmap(self.image_path)

        self.update_image()

        self.resize(self.original_pixmap.width(), self.original_pixmap.height())
        self.setMinimumSize(400, 400)

    def update_image(self):
        scaled_image = self.original_pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        self.image_label.setPixmap(scaled_image)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.update_image()


class StatusTextDelegate(QStyledItemDelegate):
    """Delegate to update colors of statuses and columns in treeview"""

    def paint(self, painter, option, index):
        """Custom override of QT paint functions
        Args:
            painter (object): Qt painter
            option (object): Qt option
            index (object): Qt Cel index
        """
        painter.save()
        icon = index.data(Qt.DecorationRole)
        text = index.data(Qt.DisplayRole)
        if not icon:
            pass
        else:
            # Draw the icon
            icon.paint(painter, option.rect.adjusted(5, 5, -5, -5), Qt.AlignRight)

        # Draw the text
        painter.drawText(option.rect.adjusted(0, 0, 0, 0), Qt.AlignLeft, text)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(30, 30)


class OptionsWidget(QWidget):
    """Dynamic Widget for the display and configuration of global options"""

    optionChanged = Signal(str, object)
    saveButtonClicked = Signal(dict)

    def __init__(self, json_data):
        """
        Args:
            json_data (dict): dictionary of options from eithr globals or studio defined file
        """
        super().__init__()
        self.data = json_data
        self.widgets = {}
        self.init_ui()

    def init_ui(self):
        """Build the dynamic UI based on special syntax in globals OPTIONS_BASE"""
        layout = QVBoxLayout()

        for key, value in self.data.items():
            is_disabled = key.startswith("#")
            display_key = key[1:] if is_disabled else key

            if isinstance(value, bool):
                widget = QCheckBox()
                widget.setChecked(value)
                widget.stateChanged.connect(
                    lambda state, k=key: self.on_change(k, state == 2)
                )
            elif isinstance(value, list):
                widget = QComboBox()
                default_item = next(
                    (item for item in value if item.endswith("*")), None
                )
                items = [item.rstrip("*") for item in value]
                if default_item:
                    default_index = value.index(default_item)
                    items[default_index] += " - Default"
                widget.addItems(items)
                if default_item:
                    widget.setCurrentIndex(default_index)
                widget.currentTextChanged.connect(
                    lambda text, k=key: self.on_change(k, self.clean_combo_value(text))
                )
            else:
                continue

            self.widgets[key] = widget
            row_layout = QHBoxLayout()
            label = QLabel(display_key)
            row_layout.addWidget(label)
            row_layout.addWidget(widget)

            if is_disabled:
                self.set_widget_disabled(widget)
                self.set_widget_disabled(label)

            layout.addLayout(row_layout)


        self.setLayout(layout)
        self.setWindowTitle("Options")

    def set_widget_disabled(self, widget):
        """Disable a widget if special # syntax requires

        Args:
            widget (object): Qt Widget to disable
        """
        widget.setEnabled(False)
        palette = widget.palette()
        palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(128, 128, 128))
        widget.setPalette(palette)

    def clean_combo_value(self, value):
        """Strip special syntax from return values

        Args:
            value (str): value to strip

        Returns:
            str: special syntax stripped value
        """
        return value.replace(" - Default", "")

    def on_change(self, key, value):
        """Trigger Signal if options change

        Args:
            key (str): the key of the dict which has changed
            value (str): the value of the dict which has changed
        """
        self.data[key] = value
        self.optionChanged.emit(key, value)

    def save_options(self):
        """Save options to a json file defined in globals"""
        cleaned_data = {
            k: self.clean_combo_value(v) if isinstance(v, str) else v
            for k, v in self.data.items()
        }
        self.saveButtonClicked.emit(cleaned_data)

    def get_current_data(self):
        """Retrieve isolated options dictionary cleaned

        Returns:
            dict: isolated options
        """

        current_data = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                current_data[key] = widget.isChecked()
            if isinstance(widget, QComboBox):
                current_data[key] = self.clean_combo_value(widget.currentText())
        return current_data


class ChangeReportSubmit(QDialog):
    """Widget to display and edit change report for all edits in the localization manifests"""

    def __init__(self, manifest_crud, sg):
        super().__init__()
        self.manifest_crud = manifest_crud
        self.manifest_crud.select_database("FOUNDRY")
        self.fn_base_entity = self.manifest_crud.read(filters=[("id", "eq", 0)])[-1]
        self.icon_data = self.fn_base_entity["icon_data"]
        self.valid_statuses = self.fn_base_entity["valid_statuses"]
        self.fn_change_entities = self.manifest_crud.read(
            filters=[
                (
                    "fn_type",
                    "in",
                    ["NewNote", "StatusChange", "NoteReply"],
                )
            ]
        )
        self.sg = sg
        self.edit_widgets = {}  # Store references to edit widgets
        self.setWindowTitle("Change Report")
        self.setGeometry(100, 100, 800, 600)


        # Main layout
        main_layout = QVBoxLayout()

        # Scroll area for content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        self.content_layout = QVBoxLayout(scroll_content)

        # Create editable content
        self.create_editable_content()

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        # Buttons
        button_layout = QHBoxLayout()
        self.submit_button = QPushButton("Submit")
        self.cancel_button = QPushButton("Cancel")
        button_layout.addWidget(self.submit_button)
        button_layout.addWidget(self.cancel_button)

        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

        # Connect buttons
        self.submit_button.clicked.connect(self.on_submit)
        self.cancel_button.clicked.connect(self.reject)

    def create_editable_content(self):
        """Creates editable widgets for each change entity"""
        self.edit_widgets.clear()

        # Header
        header = QLabel("<h1>Change Report</h1>")
        header.setStyleSheet("color: #4a9fff;")
        self.content_layout.addWidget(header)

        self.manifest_crud.select_database("SG")
        for change in self.fn_change_entities:
            # Section divider
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            self.content_layout.addWidget(line)

            # Change type header
            title = split_camel_case(change["fn_type"])
            if change["fn_type"] == "StatusChange":
                title = split_camel_case(
                    "".join([change["fn_type"], change["sg_type"]])
                )
            type_label = QLabel(
                f"<span style='color: #4a9fff; font-weight: bold;'>{title}</span>"
            )
            self.content_layout.addWidget(type_label)

            # Create widgets container for this change
            change_widget = QWidget()
            change_layout = QVBoxLayout(change_widget)

            # Get related SG entities
            sg_ids = []
            for k, v in change.items():
                if "_id" in k:
                    sg_ids.append(v)
            sg_entities = self.manifest_crud.read(filters=[("id", "in", sg_ids)])

            # Display and make entities editable
            for sg in sg_entities:
                if sg["type"] == "Version":
                    self.add_display_field(change_layout, "Version", sg["code"], False)
                    if sg.get("sg_task", None):
                        self.add_display_field(
                            change_layout, "Task", sg["sg_task"]["name"], False
                        )
                if sg["type"] == "Note":
                    self.add_display_field(
                        change_layout,
                        "Note Subject",
                        sg["subject"],
                        False,
                        f"subject_{change['id']}",
                    )

            if change["fn_type"] == "NewNote":
                subject_widget = self.add_display_field(
                    change_layout,
                    "Note Subject",
                    SG_NOTE_SUBJECT_TEMPLATE,
                    True,
                    f"subject_{change['id']}",
                )
                self.edit_widgets[f"subject_{change['id']}"] = subject_widget

            # Handle status changes
            if change.get("sg_status", None):
                status_layout = QHBoxLayout()
                current_status = self.create_status_label(change["sg_status"])
                arrow_label = QLabel(" → ")
                arrow_label.setStyleSheet("color: white;")
                entity_status_icon_data = [
                    i
                    for i in self.icon_data
                    if i["name"]
                       in self.valid_statuses[change["sg_type"]]
                ]

                # Create status combo box
                new_status_combo = QComboBox()
                new_status_combo.setStyleSheet(
                    """
                    QComboBox { 
                        background-color: #2a2a2a; 
                        color: white; 
                        border: 1px solid #4a9fff; 
                        padding: 5px;
                    }
                """
                )

                # Populate status options
                current_icon = None
                for status in entity_status_icon_data:
                    new_status_combo.addItem(
                        QIcon(status["icon_path"]), status["lname"], status["name"]
                    )
                    if status["name"] == change["new_status"]:
                        current_icon = new_status_combo.count() - 1

                if current_icon is not None:
                    new_status_combo.setCurrentIndex(current_icon)

                self.edit_widgets[f"status_{change['id']}"] = new_status_combo

                status_layout.addWidget(current_status)
                status_layout.addWidget(arrow_label)
                status_layout.addWidget(new_status_combo)
                status_layout.addStretch()
                change_layout.addLayout(status_layout)

            # Handle comments
            if change.get("comment", None):
                comment_label = QLabel("Comment:")
                comment_label.setStyleSheet("color: #4a9fff;")
                change_layout.addWidget(comment_label)

                comment_edit = QTextEdit()
                comment_edit.setStyleSheet(
                    """
                    QTextEdit { 
                        background-color: #2a2a2a; 
                        color: white; 
                        border: 1px solid #4a9fff; 
                        padding: 5px;
                    }
                """
                )
                comment_edit.setPlainText(change["comment"]["comment"])
                comment_edit.setMinimumHeight(100)
                self.edit_widgets[f"comment_{change['id']}"] = comment_edit
                change_layout.addWidget(comment_edit)

                # Handle images
                if change["comment"].get("images", None):
                    images_label = QLabel("Attached Images:")
                    images_label.setStyleSheet("color: #4a9fff;")
                    change_layout.addWidget(images_label)

                    images_widget = QWidget()
                    images_layout = QHBoxLayout(images_widget)

                    for image in change["comment"]["images"]:
                        image_frame = QFrame()
                        image_frame.setStyleSheet("border: 1px solid #4a9fff;")
                        image_layout = QVBoxLayout(image_frame)

                        # Image preview
                        image_label = QLabel()
                        pixmap = QPixmap(image)
                        scaled_pixmap = pixmap.scaled(
                            200, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        image_label.setPixmap(scaled_pixmap)

                        # Remove button
                        remove_btn = QPushButton("Remove")
                        remove_btn.setProperty("image_path", image)
                        remove_btn.setProperty("change_id", change["id"])
                        remove_btn.clicked.connect(self.remove_image)

                        image_layout.addWidget(image_label)
                        image_layout.addWidget(remove_btn)
                        images_layout.addWidget(image_frame)

                    images_layout.addStretch()
                    change_layout.addWidget(images_widget)

            self.content_layout.addWidget(change_widget)

        self.content_layout.addStretch()

    def add_display_field(
        self, layout, label_text, value, editable=False, widget_id=None
    ):
        """Adds a labeled field to the layout"""
        field_layout = QHBoxLayout()

        label = QLabel(f"{label_text}:")
        label.setStyleSheet("color: #4a9fff;")
        field_layout.addWidget(label)

        if editable:
            value_widget = QLineEdit(value)
            value_widget.setStyleSheet(
                """
                QLineEdit { 
                    background-color: #2a2a2a; 
                    color: white; 
                    border: 1px solid #4a9fff; 
                    padding: 5px;
                }
            """
            )
        else:
            value_widget = QLabel(value)
            value_widget.setStyleSheet("color: white;")

        field_layout.addWidget(value_widget)
        field_layout.addStretch()

        layout.addLayout(field_layout)
        return value_widget if editable else None

    def create_status_label(self, status_code):
        """Creates a label with status icon"""
        status_info = next(
            (s for s in self.icon_data if s["name"] == status_code), None
        )
        if status_info:
            label = QLabel()
            label.setPixmap(
                QPixmap(status_info["icon_path"]).scaled(
                    16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
            label.setToolTip(status_info["lname"])
            return label
        return QLabel(status_code)

    def remove_image(self):
        """Removes an image from a change entity"""
        sender = self.sender()
        image_path = sender.property("image_path")
        change_id = sender.property("change_id")

        # Update the manifest
        self.manifest_crud.select_database("FOUNDRY")
        for change in self.fn_change_entities:
            if change["id"] == change_id:
                if "images" in change["comment"]:
                    change["comment"]["images"].remove(image_path)
                    self.manifest_crud.update(change["id"], change)
                break

        # Refresh the display
        self.refresh_content()

    def refresh_content(self):
        """Refreshes the content display"""
        # Clear existing content
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Recreate content
        self.create_editable_content()

    def collect_changes(self):
        """Collects all changes from edit widgets"""
        updates = {}

        for widget_id, widget in self.edit_widgets.items():
            change_id = widget_id.split("_")[1]
            change_type = widget_id.split("_")[0]

            if change_id not in updates:
                updates[change_id] = {}

            if isinstance(widget, QTextEdit):
                updates[change_id]["comment"] = widget.toPlainText()
            elif isinstance(widget, QLineEdit):
                updates[change_id]["subject"] = widget.text()
            elif isinstance(widget, QComboBox):
                updates[change_id]["new_status"] = widget.currentData()

        return updates

    def update_manifest_entities(self, updates):
        """Updates the manifest entities with collected changes"""
        self.manifest_crud.select_database("FOUNDRY")

        for change in self.fn_change_entities:
            change_updates = updates.get(str(change["id"]))
            if change_updates:
                if "comment" in change_updates and change.get("comment"):
                    change["comment"]["comment"] = change_updates["comment"]
                if "subject" in change_updates:
                    change["subject"] = change_updates["subject"]
                if "new_status" in change_updates:
                    change["new_status"] = change_updates["new_status"]

                self.manifest_crud.update(change["id"], change)

    def on_submit(self):
        """Collects changes and submits them to Shotgrid"""
        # Collect all changes
        updates = self.collect_changes()

        # Update manifest entities
        self.update_manifest_entities(updates)

        # Proceed with original submission logic
        submitted = []
        for change in self.fn_change_entities:
            self.manifest_crud.select_database("SG")

            if change["fn_type"] == "NewNote":
                fn_sg_manifest_entity = self.manifest_crud.read(
                    filters=[("id", "eq", change["sg_entity_id"])]
                )[-1]
                note = sg_add_note(
                    self.sg,
                    fn_sg_manifest_entity,
                    change,
                )
                UPDATE_SIGNALS.details_text.emit(
                    False, "Submitted Note ID: " + str(note["id"])
                )
                submitted.append(note)
            if change["fn_type"] == "StatusChange":
                fn_sg_manifest_entity = self.manifest_crud.read(
                    filters=[("id", "eq", change["sg_entity_id"])]
                )[-1]
                submitted.append(
                    sg_update_status(
                        self.sg, fn_sg_manifest_entity, change["new_status"]
                    )
                )
            if change["fn_type"] == "NoteReply":
                reply = sg_add_reply(self.sg, change)
                UPDATE_SIGNALS.details_text.emit(
                    False, "Submitted Reply ID: " + str(reply["id"])
                )
                submitted.append(reply)

        if len(submitted) == len(self.fn_change_entities):
            parent_ids_for_resync = [
                x.get("parent_id") for x in self.fn_change_entities if x
            ]
            sg_manifest_parent_entities = self.manifest_crud.read(
                filters=[("id", "in", parent_ids_for_resync)]
            )
            submitted.extend(sg_manifest_parent_entities)

            for entity in submitted:
                parent_item = TreeItem(
                    name="Fake", node_type=entity["type"], data=entity
                )
                create_manifest_entities(parent_item, self.sg, self.manifest_crud)

            self.manifest_crud.select_database("FOUNDRY")
            for submitted_change in self.fn_change_entities:
                self.manifest_crud.delete(submitted_change["id"])
            hiero_update_changed_items(self.manifest_crud)
        else:
            raise Exception(
                "Partial upload to ShotGrid! halting further operation see errors and manifests to resolve"
            )

        self.accept()


class NoteStatusWidget(QWidget):
    """Widget displayed at the top of the Notes tab, Containing version status and new note buttons"""

    status_updated = Signal(int, str, str)
    new_note_requested = Signal(int)

    def __init__(
        self,
        manifest_crud,
        sg_manifest_id,
        entity_status,
        entity_type,
        icon_data,
        status_modified=None,
        parent=None,
    ):
        """
        Args:
            sg_manifest_id (int): SG id from the sg manifest or parent item in treeview
            entity_status (str): sg shortcode status from sg_status_list.
            icon_data (list): fn manifest base entity icon data dictionary pointing to status tag icons on disk
            status_modified (str, optional): modified status to drive status combo box. Defaults to None.
            parent (object, optional):. Defaults to None.
        """
        super().__init__(parent)
        self.manifest_crud = manifest_crud
        self.sg_manifest_id = sg_manifest_id
        self.entity_status = entity_status
        self.entity_type = entity_type
        self.icon_data = icon_data
        self.status_modified = status_modified
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        if not all([self.sg_manifest_id, self.entity_status]):
            no_localize_label = QLabel("Please localize to see notes")
            layout.addWidget(no_localize_label)
        else:
            create_button = QPushButton("Create New Note")
            self.manifest_crud.select_database("SG")
            sg_manifest_entity = self.manifest_crud.read(
                filters=[("id", "eq", self.sg_manifest_id)]
            )[-1]
            display_name = sg_manifest_entity.get("code") or sg_manifest_entity.get(
                "cached_display_name"
            )
            version_label = QLabel(f"{self.entity_type}: {display_name} = ")
            to_label = QLabel(" >> ")
            self.status_combo = QComboBox()
            self.status_combo.setItemDelegate(StatusTextDelegate())
            self.entity_status_icon = [
                x for x in self.icon_data if self.entity_status in x["name"]
            ][-1]

            pixmap = QPixmap(self.entity_status_icon["icon_path"])
            sg_status = QLabel()
            sg_status.setPixmap(pixmap)
            sg_status.setScaledContents(True)
            sg_status.setMaximumHeight(20)
            sg_status.setMaximumWidth(20)
            sg_status.setToolTip(self.entity_status_icon["lname"])

            self.status_combo.addItem("---")
            for status in [
                x for x in self.icon_data if x["name"] != self.entity_status
            ]:
                self.status_combo.addItem(QIcon(status["icon_path"]), status["lname"])

            if self.status_modified:
                modified_status_icon = [
                    x for x in self.icon_data if self.status_modified in x["name"]
                ][-1]
                updated_status_index = self.icon_data.index(modified_status_icon) + 1
                self.status_combo.setCurrentIndex(updated_status_index)
            else:
                self.status_combo.setCurrentIndex(0)

            self.status_combo.currentIndexChanged.connect(self.status_changed)
            create_button.clicked.connect(self.new_note)
            layout.addWidget(version_label)
            layout.addWidget(sg_status)
            layout.addWidget(to_label)
            layout.addWidget(self.status_combo)
            layout.addWidget(create_button)
            layout.setContentsMargins(2, 2, 2, 2)
        self.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def status_changed(self):
        """Emits signal to create fn manifest change entity"""
        short_name = self.status_combo.currentText()
        if short_name != "---":
            short_name = [
                x["name"]
                for x in self.icon_data
                if x["lname"] == self.status_combo.currentText()
            ][-1]

        self.status_updated.emit(
            self.sg_manifest_id,
            self.entity_status,
            short_name,
        )

    def new_note(self):
        """Emits signal to create fn manifest note entity"""
        self.new_note_requested.emit(self.sg_manifest_id)


class CommentWidget(QWidget):
    """Widget to Create edit and display SMS like messaging comments"""

    image_updated = Signal(int, list)
    reply_requested = Signal(int, str)
    edit_requested = Signal(int, str)
    delete_requested = Signal(int)

    def __init__(
        self,
        note_id,
        commenter,
        comment,
        sg_entity_id,
        image_paths=[],
        is_reply=False,
        parent=None,
    ):
        """
        Args:
            note_id (int): sg manifest id for note
            commenter (str): User who created note
            comment (str): Note contents
            image_paths (str, optional): path to image on disk. Defaults to None.
            is_reply (bool, optional): Denotes structure and speech bubble tick orientation false=left true=right.
            Defaults to False.
            parent (QObject, optional):QT parent . Defaults to None.
        """
        super().__init__(parent)
        self.note_id = note_id
        self.sg_entity_id = sg_entity_id
        self.commenter = commenter
        self.comment = comment
        self.image_paths = image_paths
        self.is_reply = is_reply
        self.annotation_layout = QVBoxLayout()
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout()
        comment_text = f"{self.commenter}:\n\n{self.comment}\n"
        if self.is_reply and self.commenter == "You":
            self.comment_label = BubbleLabel(comment_text, is_sent=True)
            self.layout.addWidget(self.comment_label)
            self.comment_label.setWordWrap(True)
        else:
            self.comment_label = BubbleLabel(comment_text)
            self.layout.addWidget(self.comment_label)
            self.comment_label.setWordWrap(True)

        self.update_images()
        button_layout = QHBoxLayout()

        if not self.is_reply and self.note_id > 0:
            reply_button = QPushButton("Reply")
            reply_button.clicked.connect(self.request_reply)
            button_layout.addWidget(reply_button)

        if self.is_reply and self.commenter == "You":
            edit_button = QPushButton("Edit")
            edit_button.clicked.connect(self.request_edit)
            button_layout.addWidget(edit_button)
            delete_button = QPushButton("Delete")
            delete_button.clicked.connect(self.request_delete)
            button_layout.addWidget(delete_button)
            add_annotation_button = QPushButton("Add Annotation")
            add_annotation_button.clicked.connect(self.add_annotation)
            button_layout.addWidget(add_annotation_button)

        button_layout.addStretch()
        self.layout.addLayout(button_layout)
        self.setLayout(self.layout)

    def add_annotation(self):
        """Applies captured annotation image to comment"""
        temp_annotation_file_path, annotation_file_path = hiero_capture_annotation(self.sg_entity_id)
        if annotation_file_path:
            if os.path.isfile(annotation_file_path):
                os.remove(temp_annotation_file_path)
                if not self.image_paths:
                    self.image_paths = []
                self.image_paths.append(annotation_file_path)
                self.update_images()
                self.image_updated.emit(self.note_id, self.image_paths)
                self.init_ui()  # Reinitialize UI to update buttons

    def update_images(self):
        """Updates image on comment"""

        if self.annotation_layout:
            while self.annotation_layout.count():
                item = self.annotation_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
                break

        for i, image in enumerate(self.image_paths):

            image_label = QLabel(os.path.normpath(image))
            pixmap = QPixmap(os.path.normpath(image))
            scaled_pixmap = pixmap.scaled(
                200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            image_label.setPixmap(scaled_pixmap)
            if self.is_reply and self.commenter == "You":
                image_label.setAlignment(Qt.AlignRight)
            tooltip = "No frame number detected"
            try:
                filename = os.path.basename(os.path.normpath(image))
                frame = filename.split(".")[1]
                if frame == "png":
                    frame = filename.split("_")[-1].split("F")[0]
                tooltip = "Annotation for Frame {}".format(frame)
            except IndexError:
                pass
            image_label.setToolTip(tooltip)
            image_label.setCursor(Qt.PointingHandCursor)
            image_label.mousePressEvent = (
                lambda event, checked=None, p=image: self.show_full_image(
                    os.path.normpath(p)
                )
            )
            self.annotation_layout.addWidget(image_label)

            if self.is_reply and self.commenter == "You":
                remove_image_button = QPushButton("Remove")
                remove_image_button.clicked.connect(
                    lambda checked=None, index=i: self.remove_annotation(index)
                )

                self.annotation_layout.addWidget(remove_image_button)

        self.layout.addLayout(self.annotation_layout)

    def request_reply(self):
        """Signal to initialize reply submission UI"""
        self.reply_requested.emit(self.note_id, "")

    def request_image(self):
        """Signal to initialize image from comment"""
        self.image_requested.emit(self.note_id)

    def request_edit(self):
        """Signal to initialize edit existing comment UI"""
        self.edit_requested.emit(self.note_id, self.comment)

    def request_delete(self):
        """Signal to initialize deletion of comment . Only applicable to self made comments"""
        self.delete_requested.emit(self.note_id)

    def remove_annotation(self, index):
        """Remove image from comment"""
        del self.image_paths[index]
        self.update_images()
        self.image_updated.emit(self.note_id, self.image_paths)
        self.init_ui()  # Reinitialize UI to update buttons

    def show_full_image(self, path):
        """Popup a dialog showing full image that was clicked"""
        dialog = ImageDialog(path, self)
        dialog.exec_()


class CommentReplyWidget(QWidget):
    """Widget to show notes and status change UIs"""

    def __init__(self, manifest_crud, sg_entity):
        super().__init__()
        self.main_layout = None
        self.comments = None
        self.manifest_crud = manifest_crud
        self.sg_entity = sg_entity
        if not self.sg_entity:
            self.init_blank()
            return
        self.manifest_crud.select_database("SG")
        self.sg_manifest_entity = self.manifest_crud.read(
            filters=[("id", "eq", sg_entity["id"])]
        )
        self.manifest_crud.select_database("FOUNDRY")
        self.fn_base_entity = self.manifest_crud.read(filters=[("id", "eq", 0)])[-1]
        self.user = get_session_user()
        self.options = self.fn_base_entity["options"]
        self.color_map = self.fn_base_entity["color_map"]
        self.icon_data = self.fn_base_entity["icon_data"]

        self.fn_status_change_entities = self.manifest_crud.read(
            filters=[("fn_type", "eq", "StatusChange")]
        )
        self.init_ui()

    def init_ui(self):
        if not self.sg_manifest_entity:
            self.init_blank()
            return
        if not self.sg_manifest_entity[-1].get("sg_status_list", None):
            self.init_blank()
            return
        if self.main_layout:
            self.clear_layout(self.main_layout)

        self.main_layout = QVBoxLayout(self)
        self.sg_manifest_entity = self.sg_manifest_entity[-1]
        modified = None
        entity_change = [
            x
            for x in self.fn_status_change_entities
            if x["sg_entity_id"] == self.sg_manifest_entity["id"]
        ]
        if entity_change:
            modified = entity_change[-1]["new_status"]
        entity_status_icon_data = [
            i
            for i in self.icon_data
            if i["name"]
            in self.fn_base_entity["valid_statuses"][self.sg_manifest_entity["type"]]
        ]
        entity_status_info = NoteStatusWidget(
            manifest_crud=self.manifest_crud,
            sg_manifest_id=self.sg_manifest_entity["id"],
            entity_status=self.sg_manifest_entity["sg_status_list"],
            entity_type=self.sg_manifest_entity["type"],
            icon_data=entity_status_icon_data,
            status_modified=modified,
        )
        entity_status_info.new_note_requested.connect(self.create_new_note)
        entity_status_info.status_updated.connect(self.create_status_change)
        self.main_layout.addWidget(entity_status_info)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        self.main_layout.addWidget(scroll_area)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        scroll_content = QWidget(scroll_area)
        self.comments_layout = QVBoxLayout(scroll_content)
        scroll_area.setWidget(scroll_content)
        self.reply_label = QLabel("Reply:", self)
        self.reply_label.hide()
        self.main_layout.addWidget(self.reply_label)
        self.reply_edit = QTextEdit(self)
        self.reply_edit.setPlaceholderText("Type your reply here...")
        self.reply_edit.hide()
        self.main_layout.addWidget(self.reply_edit)
        button_layout = QHBoxLayout()
        self.submit_button = QPushButton("Submit", self)
        self.submit_button.setProperty("sg_entity_id", self.sg_manifest_entity["id"])
        self.submit_button.clicked.connect(self.submit_note_reply_or_edit)
        self.submit_button.hide()
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self.cancel_note_reply_or_edit)
        self.cancel_button.hide()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.submit_button)
        self.main_layout.addLayout(button_layout)
        self.load_content()

    def init_blank(self):
        """
        Due to previous slowdowns if any data is none for this widget provide a layout with no info
        """
        if self.main_layout:
            self.clear_layout(self.main_layout)
        self.main_layout = QVBoxLayout(self)
        note_status_info = NoteStatusWidget(None, None, None, None, None)
        self.main_layout.addWidget(note_status_info)

    def get_status_changes(self):
        """
        Check for edits
        """
        self.manifest_crud.select_database("FOUNDRY")
        self.fn_status_change_entities = self.manifest_crud.read(
            filters=[("fn_type", "eq", "StatusChange")]
        )

    def load_content(self):
        self.get_status_changes()
        self.comments = []
        self.manifest_crud.select_database("SG")
        sg_entity_id = self.sg_manifest_entity["id"]
        note_key = "notes"
        if self.options.get("Show only open notes"):
            note_key = "open_notes"

        # __CUSTOMIZE__ note display filtering.
        sg_manifest_entity_notes = self.sg_manifest_entity.get(note_key, None)
        if sg_manifest_entity_notes:
            note_ids = [x["id"] for x in sg_manifest_entity_notes]
            sg_manifest_entity_notes = self.manifest_crud.read(
                filters=[("id", "in", note_ids)]
            )
            if self.options.get("Show only notes addressed to me"):
                sg_manifest_entity_notes = [
                    x
                    for x in sg_manifest_entity_notes
                    if self.user in x.get("addressings_to")
                ]

        self.manifest_crud.select_database("FOUNDRY")
        fn_manifest_new_notes = self.manifest_crud.read(
            filters=[
                ("sg_entity_id", "in", [sg_entity_id]),
                ("fn_type", "eq", "NewNote"),
            ],
            # sort_by="created_at",
        )

        fn_manifest_annotation_links = self.manifest_crud.read(
            filters=[
                ("fn_type", "eq", "AnnotationLink"),
            ],
        )

        fn_modified_note_statuses = [
            x for x in self.fn_status_change_entities if x.get("sg_type", "") == "Note"
        ]

        for note in sg_manifest_entity_notes:
            note_annotations = self.collect_comment_annotations(
                note, fn_manifest_annotation_links
            )
            note_images = [x.get("localize_path") for x in note_annotations if x]
            sg_note_id = note["id"]
            replies = []
            sg_manifest_entity_replies = note.get("replies", None)
            if sg_manifest_entity_replies:
                self.manifest_crud.select_database("SG")
                reply_ids = [x["id"] for x in sg_manifest_entity_replies]
                sg_manifest_entity_replies = self.manifest_crud.read(
                    filters=[("id", "in", reply_ids)]
                )
                for reply in sg_manifest_entity_replies:
                    reply_images = [
                        x.get("localize_path")
                        for x in note_annotations
                        if is_datetime_close(
                            str(x.get("created_at")), str(reply.get("created_at"))
                        )
                    ]
                    if reply_images:
                        for image in reply_images:
                            note_images.remove(image)
                    sg_reply_id = reply["id"]
                    comment, commenter = self.format_comment(reply)
                    replies.append(
                        self.build_comment(
                            id=sg_reply_id,
                            commenter=commenter,
                            comment=comment,
                            images=reply_images,
                            replies=None,
                            status=None,
                            type="sg_reply",
                        )
                    )

            self.manifest_crud.select_database("FOUNDRY")
            fn_manifest_note_replies = self.manifest_crud.read(
                filters=[
                    ("sg_note_id", "in", [sg_note_id]),
                    ("fn_type", "eq", "NoteReply"),
                ],
                # sort_by="created_at",
            )
            # TODO unsure why sort_by is not working in json_crud
            if fn_manifest_note_replies:
                for fn_reply in fn_manifest_note_replies:
                    replies.append(fn_reply["comment"])

            comment, commenter = self.format_comment(note)

            status_modified = False
            status = note["sg_status_list"]
            if [
                s for s in fn_modified_note_statuses if s["sg_entity_id"] == sg_note_id
            ]:
                status = [
                    s
                    for s in fn_modified_note_statuses
                    if s["sg_entity_id"] == sg_note_id
                ][-1]["new_status"]
                status_modified = True
            self.comments.append(
                self.build_comment(
                    id=sg_note_id,
                    commenter=commenter,
                    comment=comment,
                    images=note_images,
                    replies=replies,
                    status=status,
                    status_modified=status_modified,
                    type="sg_note",
                )
            )

        for fn_new_note in fn_manifest_new_notes:
            self.comments.append(fn_new_note["comment"])
        self.update_display()

    def collect_comment_annotations(self, entity, fn_manifest_annotation_links):
        annotations = [
            a
            for a in fn_manifest_annotation_links
            if a["sg_id"] in [x["id"] for x in entity.get("attachments", [])]
        ]
        return annotations

    def format_comment(self, entity):
        comment = ""
        comment += "Created : {}\n".format(entity.get("created_at"))

        if entity.get("updated_at"):
            comment += "Updated : {}\n".format(entity.get("updated_at"))

        comment += "\n"
        content = entity.get("content")
        if content:
            comment += entity.get("content")
        commenter = entity.get("created_by", "")

        if not commenter:
            # Note and reply have differing user fields
            commenter = entity.get("user", "")
            if not commenter:
                commenter = {"name": "Unknown"}

        return comment, commenter["name"]

    def build_comment(
        self,
        id,
        commenter,
        comment,
        images,
        replies,
        status,
        type,
        status_modified=False,
    ):
        return {
            "id": id,
            "commenter": commenter,
            "comment": comment,
            "images": images,
            "replies": replies,
            "status": status,
            "type": type,
            "status_modified": status_modified,
        }

    def update_display(self):
        self.clear_layout(self.comments_layout)
        for comment in self.comments:
            note_status_icon_data = [
                i
                for i in self.icon_data
                if i["name"] in self.fn_base_entity["valid_statuses"]["Note"]
            ]
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)

            self.comments_layout.addWidget(line)
            if comment.get("type") == "NewNote":
                new_label = QLabel("New Note :")
                comment_widget = CommentWidget(
                    comment["id"],
                    comment["commenter"],
                    comment["comment"],
                    self.sg_manifest_entity["id"],
                    image_paths=comment["images"],
                    is_reply=True,
                )
                comment_widget.edit_requested.connect(self.show_reply_edit_box)
                comment_widget.delete_requested.connect(self.delete_note_or_reply)
                comment_widget.image_updated.connect(self.update_note_or_reply_image)
                self.comments_layout.addWidget(new_label)
                self.comments_layout.addWidget(comment_widget)
            else:
                comment_label = QLabel(f"Note Id : {comment['id']}")
                self.comments_layout.addWidget(comment_label)
                if comment.get("status", None):
                    note_status_combo = QComboBox()
                    note_status_combo.setProperty("comment_id", comment["id"])
                    note_status_combo.setItemDelegate(StatusTextDelegate())
                    note_status_combo.addItem("---")
                    for status in [x for x in note_status_icon_data if x["name"]]:
                        if comment.get("status_modified"):
                            note_status_combo.addItem(
                                QIcon(status["icon_path"]), status["lname"]
                            )
                        else:
                            if status != comment["status"]:
                                note_status_combo.addItem(
                                    QIcon(status["icon_path"]), status["lname"]
                                )

                        status_icon = [
                            x
                            for x in note_status_icon_data
                            if x["name"] in comment["status"]
                        ][-1]

                        updated_status_index = (
                            note_status_icon_data.index(status_icon) + 1
                        )
                        note_status_combo.setCurrentIndex(updated_status_index)
                    note_status_combo.currentTextChanged.connect(
                        lambda text, checked=None, id=comment[
                            "id"
                        ], sg_status="*": self.create_status_change(id, sg_status, text)
                    )
                    self.comments_layout.addWidget(note_status_combo)

            if comment.get("type") != "NewNote":
                comment_widget = CommentWidget(
                    comment["id"],
                    comment["commenter"],
                    comment["comment"],
                    self.sg_manifest_entity["id"],
                    image_paths=comment["images"]
                )
                comment_widget.reply_requested.connect(self.show_reply_edit_box)
                comment_widget.edit_requested.connect(self.show_reply_edit_box)
                comment_widget.delete_requested.connect(self.delete_note_or_reply)
                comment_widget.image_updated.connect(self.update_note_or_reply_image)
                self.comments_layout.addWidget(comment_widget)
                if comment.get("replies", []):
                    for reply in comment["replies"]:
                        reply_widget = CommentWidget(
                            reply["id"],
                            reply["commenter"],
                            reply["comment"],
                            self.sg_manifest_entity["id"],
                            image_paths=reply["images"],
                            is_reply=True,
                        )
                        reply_widget.setContentsMargins(20, 0, 0, 0)
                        reply_widget.edit_requested.connect(self.show_reply_edit_box)
                        reply_widget.delete_requested.connect(self.delete_note_or_reply)
                        reply_widget.image_updated.connect(
                            self.update_note_or_reply_image
                        )
                        self.comments_layout.addWidget(reply_widget)

        self.comments_layout.addStretch()

    def show_reply_edit_box(self, comment_id, current_text):
        """Display reply UI"""
        box_type = "Reply"
        if current_text != "":
            box_type = "Edit"
            self.reply_edit.setText(current_text)
        self.reply_label.setText(f"{box_type} {comment_id}:")
        self.reply_label.show()
        self.reply_edit.show()
        if box_type == "Reply":
            self.reply_edit.clear()
        self.submit_button.setProperty("action", box_type)
        self.submit_button.setProperty("note_id", comment_id)
        self.submit_button.setText(f"Submit {box_type}")
        self.submit_button.show()
        self.cancel_button.show()

    def delete_note_or_reply(self, comment_id):
        """Delete user created reply from Foundry manifest entities"""
        self.manifest_crud.select_database("FOUNDRY")
        fn_entity = self.manifest_crud.read(
            filters=[("fn_comment_id", "eq", comment_id)]
        )
        if fn_entity:
            self.manifest_crud.delete(fn_entity[-1]["id"])
            hiero_update_changed_items(self.manifest_crud)
            self.load_content()

    def update_note_or_reply_image(self, comment_id, image_path):
        """Update created Foundry manifest entities image information"""
        self.manifest_crud.select_database("FOUNDRY")
        reply = self.manifest_crud.read(
            filters=[
                ("fn_comment_id", "in", [comment_id]),
                ("fn_type", "in", ["NoteReply", "NewNote"]),
            ]
        )[-1]
        images = []
        images.extend(image_path)
        reply["comment"]["images"] = images
        reply["images"] = images
        self.manifest_crud.update(reply["id"], reply)
        self.load_content()

    def submit_note_reply_or_edit(self):
        comment_id = self.submit_button.property("note_id")
        entity_id = self.submit_button.property("sg_entity_id")
        action = self.submit_button.property("action")
        new_text = self.reply_edit.toPlainText().strip()
        self.manifest_crud.select_database("FOUNDRY")
        fn_manifest_note_replies = self.manifest_crud.read(
            filters=[
                ("fn_type", "in", ["NoteReply", "NewNote"]),
            ],
        )
        if new_text:
            fn_comment_id = -abs(len(fn_manifest_note_replies)) - 1
            existing_images = []
            existing_fn_reply = [
                x for x in fn_manifest_note_replies if x["fn_comment_id"] == comment_id
            ]

            if action == "Edit":
                existing_fn_reply[-1]["comment"]["comment"] = new_text
                existing_fn_reply[-1]["created_at"] = datetime.datetime.now(
                    sgtimezone.LocalTimezone()
                )
                self.manifest_crud.update(
                    existing_fn_reply[-1]["id"], existing_fn_reply[-1]
                )
                self.load_content()
                self.cancel_note_reply_or_edit()
                return

            fn_type = "NoteReply"
            if not comment_id:
                fn_type = "NewNote"

            note_reply = {
                "id": "__UNIQUE__",
                "fn_comment_id": fn_comment_id,
                "sg_note_id": comment_id,
                "sg_entity_id": entity_id,
                "fn_type": fn_type,
                "comment": self.build_comment(
                    fn_comment_id,
                    "You",
                    new_text,
                    status=None,
                    status_modified=False,
                    type=fn_type,
                    images=existing_images,
                    replies=None,
                ),
                "images": existing_images,
                "created_at": datetime.datetime.now(sgtimezone.LocalTimezone()),
            }
            self.manifest_crud.create(note_reply)
            hiero_update_changed_items(self.manifest_crud)
            self.load_content()
            self.cancel_note_reply_or_edit()

    def cancel_note_reply_or_edit(self):
        """reply/edit box button signals to cancel"""
        self.reply_label.hide()
        self.reply_edit.hide()
        self.submit_button.hide()
        self.cancel_button.hide()

    def create_status_change(self, entity_id, sg_status, new_status):
        """Create Foundry manifest entity for version status change"""
        self.manifest_crud.select_database("SG")
        sg_manifest_entity = self.manifest_crud.read(filters=[("id", "eq", entity_id)])
        short_name = new_status
        if short_name != "---":
            try:
                short_name = [
                    x["name"] for x in self.icon_data if x["lname"] == new_status
                ][-1]
            except IndexError:
                pass
        if sg_manifest_entity:
            entity_type = sg_manifest_entity[-1]["type"]
            if sg_manifest_entity[-1].get("sg_status_list", None):
                if sg_status == "*":
                    sg_status = sg_manifest_entity[-1].get("sg_status_list")
                self.manifest_crud.select_database("FOUNDRY")
                existing_status_changes = self.manifest_crud.read(
                    filters=[
                        ("sg_entity_id", "in", [entity_id]),
                        ("fn_type", "eq", "StatusChange"),
                    ]
                )
                [self.manifest_crud.delete(x["id"]) for x in existing_status_changes]
                status_data = {
                    "id": "__UNIQUE__",
                    "fn_type": "StatusChange",
                    "sg_entity_id": entity_id,
                    "sg_parent_id": self.sg_manifest_entity["id"],
                    "sg_type": entity_type,
                    "sg_status": sg_status,
                    "new_status": short_name,
                    "created_at": datetime.datetime.now(sgtimezone.LocalTimezone()),
                }

                if sg_status != short_name and short_name != "---":
                    self.manifest_crud.create(status_data)
                hiero_update_changed_items(self.manifest_crud)

    def create_new_note(self):
        self.reply_label.setText(
            f"Create new comment for entity {self.sg_entity['id']}:"
        )
        self.reply_label.show()
        self.reply_edit.show()
        self.reply_edit.clear()
        self.submit_button.setProperty("action", "NewNote")
        self.submit_button.setProperty("note_id", None)
        self.submit_button.setText("Submit Note")
        self.submit_button.show()
        self.cancel_button.show()

    def clear_layout(self, layout):
        """Clear all widgets on ui refresh"""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())
