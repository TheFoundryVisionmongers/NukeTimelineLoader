import os
import sys
import shutil
from qtpy.QtCore import QRunnable, Signal, QObject, QThreadPool
from fileseq import FileSequence

import requests


class UpdateSignals(QObject):
    """
    Signals for updating ShotgridLoaderWidget.details_text from other modules
    """

    details_text = Signal(
        bool, str
    )  # bool relates to fn_ui.ShotgridLoaderWidget.update_details is_error
    # so False=Not an error True=an error which will be formatted in red in the details_text
    release_lock = Signal(bool)


# Create a global for details panel which can be updated by modules without circular imports
UPDATE_SIGNALS = UpdateSignals()


class TreeViewSignals(QObject):
    """
    Signals updating ShotgridLoaderWidget and TreePanel.
    """

    context_menu_action = Signal(list, str)  # selected items, action text
    note_selection = Signal(object)
    filmstrip_selection = Signal(object, list)
    tab_changed = Signal(int)
    search_reset = Signal(bool)
    copy_search = Signal(bool)
    details_text = Signal(bool, str)


class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker. Used in DataFetcher
    """

    data_fetched = Signal(object, list)  # parent_item, child_items
    remove_placeholder = Signal(object)
    finished = Signal(bool)


class DataFetcher(QRunnable):
    """
    Worker class for fetching data in a separate instanced thread
    """

    def __init__(
        self, fetch_func, parent_item, sg_instance_pool, signals=None, **kwargs
    ):
        """

        Args:
            fetch_func (func): function pointer from schema to retrieve child data
            parent_item (QObject): parent fn_model.TreeItem which may or may not be used in the function pointer
            sg_instance_pool (Object): instanced fn_sg_func.SgInstancePool to handle checkout of threaded SG instances
            signals (QObject):  WorkerSignals for communication to fn_model.LazyTreeModel
            **kwargs: fetch_func extra keyword arguments if required
        """
        super(DataFetcher, self).__init__()
        self.fetch_func = fetch_func
        self.parent_item = parent_item
        self.sg_instance_pool = sg_instance_pool
        self.signals = signals or WorkerSignals()
        self.kwargs = kwargs

    def run(self):
        sg_instance = self.sg_instance_pool.get_sg_instance()
        try:
            result = self.fetch_func(self.parent_item, sg_instance, **self.kwargs)
            self.signals.data_fetched.emit(self.parent_item, result)
        except:
            traceback_info = sys.exc_info()
            exctype, value, tb = traceback_info
            while tb.tb_next:
                tb = tb.tb_next
            func_name = tb.tb_frame.f_code.co_name
            line_no = tb.tb_lineno
            UPDATE_SIGNALS.details_text.emit(
                True,
                f"DataFetcher Error in function {func_name} at line {line_no}: {str(value)}",
            )
            self.signals.data_fetched.emit(self.parent_item, [])
        finally:
            self.sg_instance_pool.release_sg_instance(sg_instance)
            if self.sg_instance_pool.is_finished():
                self.signals.remove_placeholder.emit(self.parent_item)
                self.signals.finished.emit(True)


class DownloadWorkerSignals(QObject):
    """Signals for use in SGDownloadWorker"""

    progress = Signal(str, int)
    finished = Signal(str)


class SGDownloaderSignals(QObject):
    """Signals for use in SGDownloader"""

    done = Signal()


class SGDownloadWorker(QRunnable):
    """Separate Threaded Download worker"""

    def __init__(self, sg_instance_pool, download_file_path, sg_url, signals=None):
        """
        Args:
            download_file_path (str): path to create downloaded file
            sg_url (str): Url to download from
            signals (QObject): Signals DownloadWorkerSignals
        """
        super().__init__()
        self.sg_instance_pool = sg_instance_pool
        self.signals = signals or DownloadWorkerSignals()
        self.url = sg_url
        self.download_file_path = download_file_path

    def run(self):
        sg_instance = self.sg_instance_pool.get_sg_instance()

        try:
            attachment = {"url": self.url}
            result = sg_instance.download_attachment(
                attachment, self.download_file_path
            )
            if not result:
                raise Exception("unable to download {}".format(self.url))
        except:
            traceback_info = sys.exc_info()
            exctype, value, tb = traceback_info
            while tb.tb_next:
                tb = tb.tb_next
            func_name = tb.tb_frame.f_code.co_name
            line_no = tb.tb_lineno
            UPDATE_SIGNALS.details_text.emit(
                True,
                f"SGDownloadWorker Error in function {func_name} at line {line_no}: {str(value)}",
            )
        finally:
            self.sg_instance_pool.release_sg_instance(sg_instance)
            self.signals.finished.emit(self.download_file_path)


class SGDownloader:
    """Class to handle the threaded download of multiple files from SG"""

    def __init__(self, manifest_crud, selected_ids, sg_instance_pool):
        """
        Args:
            manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
            selected_ids (list): of int FN manifest version ids for download
        """
        super().__init__()
        self.sg_instance_pool = sg_instance_pool
        self.manifest_crud = manifest_crud
        self.manifest_crud.select_database("FOUNDRY")
        self.download_list = self.manifest_crud.read(
            filters=[
                ("id", "in", selected_ids),
                ("localize_type", "eq", "Download"),
                ("localized", "eq", False),
            ]
        )
        self.thread_pool = QThreadPool().globalInstance()
        self.signals = SGDownloaderSignals()
        self.total_downloads = len(self.download_list)
        self.downloaded_files = 0

    def start_downloads(self):
        """Start Threads for download"""
        for dl in self.download_list:
            worker = SGDownloadWorker(
                self.sg_instance_pool, dl["download_file_path"], dl["sg_url"]
            )
            worker.signals.finished.connect(self.on_file_download)
            self.thread_pool.start(worker)

    def on_file_download(self, file_path):
        """Receive worker.signals.finished.connect and check if queue is complete firing self.signals.done"""
        self.downloaded_files += 1
        progress = int(self.downloaded_files / self.total_downloads * 100)
        UPDATE_SIGNALS.details_text.emit(
            False, f"Downloaded {file_path}. Overall progress: {progress}%"
        )

        if self.total_downloads == self.downloaded_files:
            UPDATE_SIGNALS.details_text.emit(False, f"Downloads Finished!!")
            UPDATE_SIGNALS.details_text.emit(
                False, f"Adding Files to Bin. Please wait..."
            )
            self.signals.done.emit()


class CopyWorkerSignals(QObject):
    """Signals for use in FileCopyWorker"""

    finished = Signal(str)


class FileCopyWorker(QRunnable):
    """Separate Threaded Copier worker"""

    def __init__(self, source_file, dest_file):
        """
        Args:
            source_file (str): path to source file
            dest_file (str): path to destination file
        """
        super().__init__()
        self.source_file = source_file
        self.dest_file = dest_file
        self.signals = CopyWorkerSignals()

    def run(self):
        try:
            os.makedirs(os.path.dirname(self.dest_file), exist_ok=True)
            shutil.copy2(self.source_file, self.dest_file)
            self.signals.finished.emit(self.dest_file)
        except:
            traceback_info = sys.exc_info()
            exctype, value, tb = traceback_info
            while tb.tb_next:
                tb = tb.tb_next
            func_name = tb.tb_frame.f_code.co_name
            line_no = tb.tb_lineno
            UPDATE_SIGNALS.details_text.emit(
                True,
                f"FileCopyWorker Error in function {func_name} at line {line_no}: {str(value)}",
            )


class SequenceCopierSignals(QObject):
    """Signals for use in ImageSequenceCopier"""

    progress = Signal(int)
    done = Signal()


class ImageSequenceCopier:
    """Class to handle copying of files and image sequences with instanced threading"""

    def __init__(self, manifest_crud, selected_ids):
        """
        Args:
            manifest_crud (object): instantiated fn_crud.JsonCRUD passed by fn_ui.ShotgridLoaderWidget
            selected_ids (list): of int FN manifest version ids to copy
        """
        self.manifest_crud = manifest_crud
        self.manifest_crud.select_database("FOUNDRY")

        self.sequence_list = self.manifest_crud.read(
            filters=[
                ("sg_version_ids", "in", selected_ids),
                ("localize_type", "eq", "Copy"),
                ("localized", "eq", False),
            ]
        )
        self.total_sequences = len(self.sequence_list)
        self.completed_sequences = 0
        self.thread_pool = QThreadPool()
        self.signals = SequenceCopierSignals()

    def start_copy(self):
        for sequence_info in self.sequence_list:
            self.copy_sequence(sequence_info)

    def copy_sequence(self, sequence_info):
        """Start Threads for copy"""
        source_seq = FileSequence(sequence_info["sg_source"])
        dest_seq = FileSequence(sequence_info["copy_file_path"])

        for src_file, dst_file in zip(source_seq, dest_seq):
            worker = FileCopyWorker(src_file, dst_file)
            worker.signals.finished.connect(self.on_file_copied)
            self.thread_pool.start(worker)

    def on_file_copied(self, file_path):
        """Receive worker.signals.finished.connect and check if queue is complete firing self.signals.done"""
        if self.is_sequence_complete(file_path):
            self.completed_sequences += 1
            progress = int(self.completed_sequences / self.total_sequences * 100)
            self.signals.progress.emit(progress)
            UPDATE_SIGNALS.details_text.emit(
                False,
                f"Copied Image Sequence {file_path}. Overall progress: {progress}%",
            )

            if self.completed_sequences == self.total_sequences:
                self.signals.done.emit()
                UPDATE_SIGNALS.details_text.emit(
                    False, "All sequences copied successfully!"
                )

    def is_sequence_complete(self, file_path):
        """Check if all files for a sequence are complete"""
        for sequence_info in self.sequence_list:
            source_seq = FileSequence(sequence_info["source"])
            if file_path in source_seq:
                return file_path == source_seq[-1]
        return False
