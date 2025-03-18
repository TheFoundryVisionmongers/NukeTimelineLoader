"""
Module that contains a Mongo like Create Read Update Delete system for manifests
The manifests hold data that is synced from the production tracking database and internal operations for the NT Loader
tool.
Databases used in NT Loader:
'SG' contains unaltered Shotgrid/Flow entity information which is used repeatedly to provide performant UI functionality
'FOUNDRY' contains operational entities to help construct bin entries, timeline construction and status/note/annotation
edits
"""

import json
import os
from datetime import datetime
from copy import deepcopy


class JsonCRUD:
    """
    A class that implements CRUD (Create, Read, Update, Delete) operations for multiple JSON databases.

    This class provides methods to manipulate lists of dictionaries stored in multiple JSON files.
    It supports creating, reading, updating, deleting, and upserting entities, as well as
    filtering and sorting the data across different databases.

    Attributes:
        databases (dict): A dictionary of database names to file paths.
        data (dict): A dictionary of database names to lists of entities.
        current_db (str): The name of the currently selected database.
    """

    def __init__(self, database_paths):
        """
        Initialize the JsonCRUD object with multiple databases.

        Args:
            database_paths (dict): A dictionary mapping database names to file paths.
        """
        self.database_directory = None
        self.databases = database_paths
        self.data = {}
        self.current_db = None

    def set_database_directory(self, database_directory):
        """
        Update the root directory of the required database json and load the data
        """
        self.database_directory = database_directory
        databases = {}
        for db_name, file_path in self.databases.items():
            databases.update(
                {db_name: os.path.join(self.database_directory, file_path)}
            )
        self.databases = databases
        self.load_all_data()

    def load_all_data(self):
        """
        Load data from all specified JSON files.
        """
        for db_name, file_path in self.databases.items():
            try:
                with open(file_path, "r") as file:
                    self.data[db_name] = json.load(file)
            except FileNotFoundError:
                self.data[db_name] = []

    def get_database_directory(self):
        """
        Returns the root database directory
        Returns:
            str: path to database directory
        """
        return self.database_directory

    def save_data(self, db_name=None):
        """
        Save the current data to the specified JSON file.

        Args:
            db_name (str, optional): The name of the database to save. If None, saves the current database.
        """
        db_name = db_name or self.current_db
        if db_name not in self.databases:
            raise ValueError(f"Database '{db_name}' not found.")

        with open(self.databases[db_name], "w") as file:
            json.dump(self.data[db_name], file, indent=2, default=str)

    def select_database(self, db_name):
        """
        Select a database for subsequent operations.

        Args:
            db_name (str): The name of the database to select.

        Raises:
            ValueError: If the specified database name is not found.
        """
        if db_name not in self.databases:
            raise ValueError(f"Database '{db_name}' not found.")
        self.current_db = db_name

    def which_database(self):
        """return currently selected database . Useful for threaded race conditions"""
        return self.current_db

    def clear_database(self, db_name):
        """
        Warning clears all existing data in selected database
        """
        self.data[db_name] = []
        self.save_data(db_name)

    def create(self, new_entity):
        """
        Create a new entity and add it to the current database.

        If a field in the new_entity has the value "__UNIQUE__", it will be replaced
        with a unique integer ID.

        Args:
            new_entity (dict): The new entity to be added.

        Returns:
            dict: The created entity with any "__UNIQUE__" fields replaced.

        Raises:
            ValueError: If no database is selected.
        """
        if not self.current_db:
            raise ValueError("No database selected. Use select_database() first.")

        for key, value in new_entity.items():
            if value == "__UNIQUE__":
                new_entity[key] = self.generate_unique_id(key)
        self.data[self.current_db].append(new_entity)
        self.save_data()
        return new_entity

    def generate_unique_id(self, key):
        """
        Generate a unique integer ID for a given key in the current database.

        Args:
            key (str): The key for which to generate a unique ID.

        Returns:
            int: A unique integer ID.

        Raises:
            ValueError: If no database is selected.
        """
        if not self.current_db:
            raise ValueError("No database selected. Use select_database() first.")

        existing_ids = [
            entity.get(key, 0)
            for entity in self.data[self.current_db]
            if isinstance(entity.get(key), int)
        ]
        return max(existing_ids + [0]) + 1

    def read(self, filters=None, sort_by=None, sort_order="asc"):
        """
        Read and return entities from the current database based on optional filters and sorting criteria.

        Args:
            filters (list of tuple, optional): A list of (key, operator, value) tuples for filtering.
                Supported operators are 'eq', 'in', 'gt', and 'lt'.
            sort_by (str, optional): The key to sort the results by.
            sort_order (str, optional): The sort order, either 'asc' or 'desc'. Defaults to 'asc'.

        Returns:
            list: A list of entities that match the filters, sorted as specified.

        Raises:
            ValueError: If no database is selected.
        """
        if not self.current_db:
            raise ValueError("No database selected. Use select_database() first.")

        result = self.data[self.current_db]

        if filters:
            result = self.apply_filters(result, filters)

        if sort_by:
            result = self.sort_data(result, sort_by, sort_order)

        return result

    def apply_filters(self, data, filters):
        """
        Apply filters to the data.

        Args:
            data (list): The list of entities to filter.
            filters (list of tuple): A list of (key, operator, value) tuples for filtering.

        Returns:
            list: A list of entities that match all the filters.
        """

        def check_condition(item, key, operator, value):
            if key not in item:
                return False
            if operator == "eq":
                return item[key] == value
            elif operator == "in":
                return item[key] in value
            elif operator == "gt":
                return self.compare_values(item[key], value) > 0
            elif operator == "lt":
                return self.compare_values(item[key], value) < 0
            return False

        return [
            item
            for item in data
            if all(check_condition(item, key, op, value) for key, op, value in filters)
        ]

    def compare_values(self, a, b):
        """
        Compare two values, handling datetime strings.

        Args:
            a: The first value to compare.
            b: The second value to compare.

        Returns:
            int: -1 if a < b, 0 if a == b, 1 if a > b.
        """
        if isinstance(a, str) and isinstance(b, str):
            try:
                a = datetime.fromisoformat(a)
                b = datetime.fromisoformat(b)
            except ValueError:
                pass
        return (a > b) - (a < b)

    def sort_data(self, data, sort_by, sort_order):
        """
        Sort the data based on a specified key and order.

        Args:
            data (list): The list of entities to sort.
            sort_by (str): The key to sort by.
            sort_order (str): The sort order, either 'asc' or 'desc'.

        Returns:
            list: The sorted list of entities.
        """
        reverse = sort_order.lower() == "desc"
        return sorted(data, key=lambda x: x.get(sort_by, ""), reverse=reverse)

    def update(self, entity_id, updates):
        """
        Update an existing entity in the current database.

        Args:
            entity_id: The ID of the entity to update.
            updates (dict): The updates to apply to the entity.

        Returns:
            dict: The updated entity, or None if no entity with the given ID was found.

        Raises:
            ValueError: If no database is selected.
        """
        if not self.current_db:
            raise ValueError("No database selected. Use select_database() first.")

        for entity in self.data[self.current_db]:
            if entity.get("id") == entity_id:
                self.deep_update(entity, updates)
                self.save_data()
                return entity
        return None

    def deep_update(self, target, source):
        """
        Perform a deep update of a dictionary.

        This method updates the target dictionary with values from the source dictionary,
        handling nested dictionaries and lists.

        Args:
            target (dict): The dictionary to update.
            source (dict): The dictionary containing the updates.
        """
        for key, value in source.items():
            if (
                isinstance(value, dict)
                and key in target
                and isinstance(target[key], dict)
            ):
                self.deep_update(target[key], value)
            elif (
                isinstance(value, list)
                and key in target
                and isinstance(target[key], list)
            ):
                target[key] = self.update_list(target[key], value)
            else:
                target[key] = value

    def update_list(self, target_list, source_list):
        """
        Update a list, handling nested dictionaries.

        Args:
            target_list (list): The original list to update.
            source_list (list): The list containing the updates.

        Returns:
            list: The updated list.
        """
        result = []
        for i, item in enumerate(source_list):
            if i < len(target_list):
                if isinstance(item, dict) and isinstance(target_list[i], dict):
                    new_item = deepcopy(target_list[i])
                    self.deep_update(new_item, item)
                    result.append(new_item)
                else:
                    result.append(item)
            else:
                result.append(item)
        return result

    def delete(self, entity_id):
        """
        Delete an entity with the given ID from the current database.

        Args:
            entity_id: The ID of the entity to delete.

        Returns:
            bool: True if an entity was deleted, False otherwise.

        Raises:
            ValueError: If no database is selected.
        """
        if not self.current_db:
            raise ValueError("No database selected. Use select_database() first.")

        for i, entity in enumerate(self.data[self.current_db]):
            if entity.get("id") == entity_id:
                del self.data[self.current_db][i]
                self.save_data()
                return True
        return False

    def upsert(self, entity):
        """
        Update an existing entity or insert a new one if it doesn't exist in the current database.

        If the entity has an 'id' that matches an existing entity, it will be updated.
        Otherwise, a new entity will be created.

        Args:
            entity (dict): The entity to upsert.

        Returns:
            dict: The upserted (updated or created) entity.

        Raises:
            ValueError: If no database is selected.
        """
        if not self.current_db:
            raise ValueError("No database selected. Use select_database() first.")

        entity_id = entity.get("id")
        if entity_id is None or entity_id == "__UNIQUE__":
            return self.create(entity)

        existing_entity = next(
            (e for e in self.data[self.current_db] if e.get("id") == entity_id), None
        )
        if existing_entity:
            self.deep_update(existing_entity, entity)
            self.save_data()
            return existing_entity
        else:
            return self.create(entity)
