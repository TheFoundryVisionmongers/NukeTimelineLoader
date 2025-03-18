from qtpy.QtCore import (
    Qt,
    QAbstractItemModel,
    QModelIndex,
    QThreadPool,
    Signal,
    QObject,
    QTimer,
    QSortFilterProxyModel,
)

from nt_loader.fn_workers import DataFetcher
from nt_loader.fn_sg_func import SgInstancePool
from nt_loader.fn_manifest_func import check_localized, check_sync, check_edits


class TreeItem:
    """Generic TreeItem. The hope is that the model and items are generic enough to be used for alternative purposes
    not related to production tracking. self.data is a catch-all for content that may need to be unpacked down stream.
    In this usage it contains extraneous shotgrid fields
    """

    def __init__(
        self,
        name,
        parent=None,
        node_type="root",
        item_status=None,
        data=None,
        schema=None,
        live_columns=None,
    ):
        """
        Args:
            name (str): name of the index item represented in first column
            parent (QObject): Parent TreeItem used to understand parent child relationships in LazyTreeModel. Defaults
            None.
            node_type (str): the type of entity displayed in column 2. Required to map functionality to schema for child
            retrieving function pointers.
            item_status (str) : Status of entity. This can be considered reusable for any tracking software that contains a status
            data (dict): catchall object for extra information required downstream. IE: for manifest entity creation
            schema (dict): Treeview schema with child data retrieval function pointers
        """
        self.name = name
        self.parent = parent
        self.node_type = node_type
        self.item_status = item_status
        self.children = []
        self.loaded = False
        self.loading = False
        self.schema = schema
        self.data = data

    def child_count(self):
        return len(self.children)

    def child(self, row):
        return self.children[row]

    def row(self):
        if self.parent:
            return self.parent.children.index(self)
        return 0

    def append_child(self, child_item):
        if child_item.name not in [child.name for child in self.children]:
            self.children.append(child_item)

    def remove_row(self, row_index):
        if 0 <= row_index < len(self.children):
            self.children.pop(row_index)

    def add_loading_placeholder(self):
        loading_item = TreeItem(
            name="Loading...", parent=self, node_type="Loading", schema=self.schema
        )
        self.children.insert(0, loading_item)

    def can_have_children(self):
        return self.node_type in self.schema and bool(self.schema[self.node_type])

    def sg_get_parent_name(self, node_type):
        parent = self.parent
        while parent:
            if parent.node_type == node_type:
                return parent.name
            parent = parent.parent
        return None


# Custom model implementing lazy loading
class LazyTreeModel(QAbstractItemModel):
    """Mostly Generic Tree Model. This Model utilizes a threadsafe approach to SG instance handling for the expansion
    of parent child hierarchies. __CUSTOMIZE__ if a differing approach is required to collect data this class can be
    overridden to accept a different instance pool approach to retrieve data IE: data is in different production DB .
    This would need to be reflected in the schema maps child unpacking function pointers.
    Additional to this there are examples of a mixed approach where the DataFetcher worker simply ignores the
    sg_instance argument and returns item data IE: some items data is retrieved from extra sidecar database

    """

    def __init__(
        self,
        parent=None,
        schema=None,
        non_context_items=None,
        instance_pool=None,
        manifest_crud=None,
    ):
        """

        Args:
            parent (QObject): Qt parent for widget/window attachment
            schema (dict): Treeview schema with child data retrieval function pointers
            non_context_items (list): Skip items in the provided list. globals set in fn_globals.NON_CONTEXT_ENTITIES
            instance_pool (object) : Instantiated class object which has queued pool of connections
            manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget.tree_panel
        """
        super(LazyTreeModel, self).__init__(parent)
        self.schema = schema
        self.non_context_items = non_context_items
        self.instance_pool = instance_pool or SgInstancePool(maxsize=5)
        self.manifest_crud = manifest_crud

        self.root_item = TreeItem(name="Root", node_type="root", schema=self.schema)
        self.thread_pool = QThreadPool()
        self.sorting = "name"
        self.search_mode = False  # Add search_mode flag
        self.root_item.loaded = False  # Root is not loaded initially
        self.fetchMore(QModelIndex())  # Start fetching root items
        self._tree_cache = None
        self._filter_cache = {}
        self._sort_exclusions = {"No Data", "Loading"}

    def reset_data(self):
        self.beginResetModel()
        self.root_item = TreeItem(name="Root", node_type="root", schema=self.schema)
        self.search_mode = False  # Ensure search mode is False when resetting data
        self.root_item.loaded = False
        self.endResetModel()
        # After resetting the model, trigger fetching of the root item
        self.fetchMore(QModelIndex())

    def set_schema(self, schema):
        self.schema = schema
        self.reset_data()

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()
        return parent_item.child_count()

    def columnCount(self, parent=QModelIndex()):
        return 6

    def data(self, index, role):
        if not index.isValid():
            return None
        item = index.internalPointer()
        column = index.column()
        if role == Qt.DisplayRole:
            if column == 0:
                return item.name
            elif column == 1:
                return item.node_type
            elif column == 2:
                return item.item_status
            if item.data:
                # update live columns
                if column == 3:
                    return check_localized(
                        item, self.manifest_crud, self.non_context_items
                    )
                if column == 4:
                    return check_sync(item, self.manifest_crud, self.non_context_items)
                if column == 5:
                    return check_edits(item, self.manifest_crud, self.non_context_items)
        elif role == Qt.DecorationRole and item.node_type == "Loading":
            return None
        return None

    def itemFromIndex(self, index):
        if index.isValid():
            return index.internalPointer()
        return self.root_item

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section == 0:
                return "Name"
            elif section == 1:
                return "Type"
            elif section == 2:
                return "Status"
            elif section == 3:
                return "Local"
            elif section == 4:
                return "Synced"
            elif section == 5:
                return "Edits"
        return super(LazyTreeModel, self).headerData(section, orientation, role)

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()
        if row >= parent_item.child_count():
            return QModelIndex()
        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        child_item = index.internalPointer()
        parent_item = getattr(child_item, "parent", None)
        if parent_item == self.root_item or not parent_item:
            return QModelIndex()
        grandparent_item = parent_item.parent
        if grandparent_item:
            row = grandparent_item.children.index(parent_item)
        else:
            row = 0
        return self.createIndex(row, 0, parent_item)

    def hasChildren(self, parent):
        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()
        if self.search_mode and parent_item.node_type == "Search":
            # In search mode, root item has children only if there are search results
            return parent_item.child_count() > 0
        # Nodes have children if they can have children, even if not loaded yet
        return parent_item.can_have_children()

    def canFetchMore(self, parent):
        parent_item = parent.internalPointer() if parent.isValid() else self.root_item
        if self.search_mode and parent_item == self.root_item:
            # Do not fetch more for root item when in search mode
            return False
        return (
            parent_item.can_have_children()
            and not parent_item.loaded
            and not parent_item.loading
        )

    def fetchMore(self, parent):
        parent_item = parent.internalPointer() if parent.isValid() else self.root_item
        if self.search_mode and parent_item == self.root_item:
            # Do not fetch more for root item when in search mode
            return
        if not parent_item.loaded and not parent_item.loading:
            # Add loading placeholder
            self.beginInsertRows(
                parent, parent_item.child_count(), parent_item.child_count()
            )
            parent_item.add_loading_placeholder()
            self.endInsertRows()
            parent_item.loading = True  # Set loading to True
            QTimer.singleShot(
                0, lambda: self.fetch_data(parent_item)
            )  # Ensure fetch_data is called after UI updates

    def fetch_data(self, parent_item):
        if self.search_mode and parent_item == self.root_item:
            # Do not fetch data for root item when in search mode
            return
        child_types = self.schema.get(parent_item.node_type, {})
        for child_type, fetch_func in child_types.items():
            if child_type != "_searchable":
                # Use a worker to fetch data
                worker = DataFetcher(
                    fetch_func=fetch_func,
                    parent_item=parent_item,
                    sg_instance_pool=self.instance_pool,
                )
                worker.signals.data_fetched.connect(self.on_data_fetched)
                worker.signals.remove_placeholder.connect(self.remove_placeholder)
                self.thread_pool.start(worker)

    def on_data_fetched(self, parent_item, child_data):
        parent_index = self.index_from_item(parent_item)

        # Remove placeholder before adding new items
        self.remove_placeholder(parent_item)

        # Insert new child items
        if child_data[-1]["node_type"] != "No Data":
            start_row = parent_item.child_count()
            end_row = start_row + len(child_data) - 1
            self.beginInsertRows(parent_index, start_row, end_row)
            for item_info in child_data:
                name = item_info["name"]
                node_type = item_info["node_type"]
                item_status = item_info.get("item_status")
                data = item_info.get("data")
                child_item = TreeItem(
                    name=name,
                    parent=parent_item,
                    node_type=node_type,
                    item_status=item_status,
                    data=data,
                    schema=self.schema,
                )
                parent_item.append_child(child_item)
            self.endInsertRows()
        else:
            start_row = parent_item.child_count()
            self.beginInsertRows(parent_index, start_row, start_row)
            child_item = TreeItem(
                name=child_data[-1]["name"],
                parent=parent_item,
                node_type="No Data",
                schema=self.schema,
            )
            parent_item.append_child(child_item)
            self.endInsertRows()

        parent_item.loaded = True
        parent_item.loading = False
        self.sort_by(parent_item)

    def sort_by(self, parent_item):
        if self.sorting == "name":
            self.root_item.children.sort(
                key=lambda x: (x.node_type not in self._sort_exclusions, x.name.lower())
            )
            parent_item.children.sort(
                key=lambda x: (x.node_type not in self._sort_exclusions, x.name.lower())
            )
        if self.sorting == "date":
            self.root_item.children.sort(
                key=lambda x: (
                    x.node_type not in self._sort_exclusions,
                    str(x.data.get("updated_at", 0)) if x.data else 0,
                ),
                reverse=True,
            )
            parent_item.children.sort(
                key=lambda x: (
                    x.node_type not in self._sort_exclusions,
                    str(x.data.get("updated_at", 0)) if x.data else 0,
                ),
                reverse=True,
            )

    # Silent hard DCC crash on below code. Previous attempts to use QT based filter and sort classes cause same issue
    # This means treeview needs to reset on change of sorting and inhibits column based sorting
    # def sort_by(self, parent_item):
    #     """Sort items in-place by maintaining tree structure and view state"""
    #     if not parent_item:
    #         return
    #
    #     if parent_item.node_type == "Loading":
    #         return
    #
    #     def sort_key(item):
    #         if self.sorting == "name":
    #             return (item.node_type not in self._sort_exclusions, item.name.lower())
    #         elif self.sorting == "date":
    #             if not item.data:
    #                 return (item.node_type not in self._sort_exclusions, "0")
    #             return (
    #                 item.node_type not in self._sort_exclusions,
    #                 str(item.data.get("updated_at", "0")),
    #             )
    #
    #     # Get the parent index
    #     parent_index = self.index_from_item(parent_item)
    #
    #     if parent_item.children:
    #         # Notify view that we're about to change the item order
    #         self.beginMoveRows(
    #             parent_index, 0, len(parent_item.children) - 1, parent_index, 0
    #         )
    #
    #         # Sort the children
    #         parent_item.children.sort(key=sort_key, reverse=(self.sorting == "date"))
    #
    #         # Notify view that we're done moving items
    #         self.endMoveRows()
    #
    #         # Emit dataChanged to refresh the view
    #         first = self.index(0, 0, parent_index)
    #         last = self.index(
    #             len(parent_item.children) - 1, self.columnCount() - 1, parent_index
    #         )
    #         self.dataChanged.emit(first, last, [Qt.DisplayRole])
    #
    #         # Recursively sort children's children
    #         for child in parent_item.children:
    #             if child.loaded and child.children:
    #                 self.sort_by(child)

    def refresh_tree(self):
        # Emit dataChanged to refresh the view
        first = self.index(0, 0, QModelIndex())
        last = self.index(
            len(self.root_item.children) - 1, self.columnCount() - 1, QModelIndex()
        )
        self.dataChanged.emit(first, last, [Qt.DisplayRole])

    def remove_placeholder(self, parent_item):
        # Only attempt to remove if there are children and the first one is a loading placeholder
        if (
            parent_item.child_count() > 0
            and parent_item.children[0].node_type == "Loading"
        ):
            parent_index = self.index_from_item(parent_item)
            self.beginRemoveRows(parent_index, 0, 0)
            parent_item.remove_row(0)
            self.endRemoveRows()

    def index_from_item(self, item):
        if item == self.root_item or not item.parent:
            return QModelIndex()
        else:
            parent_item = item.parent
            row = parent_item.children.index(item)
            return self.createIndex(row, 0, item)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        item = index.internalPointer()
        # Make 'Project' and 'Loading' nodes not selectable
        if item.node_type in self.non_context_items:
            return Qt.ItemIsEnabled  # Not selectable
        if item.node_type in ("Loading", "No Data", "Search"):
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def update_item(self, item):
        index = self.index_from_item(item)
        self.dataChanged.emit(index, index)

    def filter(self, text):
        if not self._tree_cache:
            self._tree_cache = self.root_item

        self.search_mode = True
        search_text = text.lower()

        if not search_text:
            self._filter_cache.clear()
            self._reset_filter()
            return

        matching_items = []
        self._filter_recursive(self._tree_cache, search_text, matching_items)
        self._filter_cache[search_text] = matching_items
        self._apply_cached_results(matching_items)

    def _apply_cached_results(self, matched_items):

        self.beginResetModel()
        self.root_item = TreeItem(
            name="Filter Results", node_type="root", schema=self.schema
        )
        self.root_item.loaded = False

        for item in matched_items:
            filter_item = TreeItem(
                name=item.name,
                node_type=item.node_type,
                item_status=item.item_status,
                data=item.data,
                schema=self.schema,
            )
            self.root_item.append_child(filter_item)

        if not matched_items:
            no_filter = TreeItem(
                name="No items in current tree cache. Try searching",
                node_type="No Data",
                schema=self.schema,
            )
            self.root_item.append_child(no_filter)
        self.endResetModel()

    def _filter_recursive(self, item, search_text, matching_items):
        found = []
        columns = [item.name, item.node_type, item.item_status]
        for c in columns:
            if c:
                if search_text in c.lower():
                    found.append(item)

        if len(found) > 0:
            matching_items.append(found[-1])

        if item.loaded:
            for child in item.children:
                self._filter_recursive(child, search_text, matching_items)

    def _reset_filter(self):
        self.beginResetModel()
        self.root_item = self._tree_cache
        self._tree_cache = None  # Ensure search mode is False when resetting data
        self.root_item.loaded = True
        self.endResetModel()
