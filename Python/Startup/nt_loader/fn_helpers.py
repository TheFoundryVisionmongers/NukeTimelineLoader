from datetime import datetime
import cv2
import platform
import os
import re
import numpy as np

from nt_loader.fn_globals import SG_MEDIA_PATH_MAP

CURRENT_OS = platform.platform(terse=True)

def is_datetime_close(date_string1, date_string2, tolerance=20):
    """
    Used to identify if a reply annotation image belongs to a reply or a note . if the creation time is within 60 seconds
    it is likely a image that needs to be assigned to the reply
    Args:
        date_string1: (str) date time in SG format
        date_string2: (str) date time in SG format
        tolerance: (int) in seconds for acceptable tolerance defaults to 60 seconds

    Returns:
        (bool) True or False if the delta fits in the acceptable tolerance

    """
    # Initialize date times from strings
    datetime1 = datetime.fromisoformat(date_string1)
    datetime2 = datetime.fromisoformat(date_string2)

    # calculate difference
    difference_seconds = abs((datetime2 - datetime1).total_seconds())
    return difference_seconds <= tolerance


def split_camel_case(string):
    """String function to space a camel case string

    Args:
        string (str): camel case string for formatting to spaces

    Returns:
        (str): spaced formated string
    """
    result = string[0].upper()
    for character in string[1:]:
        if character.isupper():
            result += " " + character
        else:
            result += character
    return result


def find_frame_bounds(reference_image):
    """
    Find the boundaries of the actual image content in the reference image.
    This helps determine the proper cropping frame.

    Args:
        reference_image: The unedited reference image

    Returns:
        tuple: (x, y, w, h) coordinates of the content bounds
    """
    # Convert to grayscale if not already
    if len(reference_image.shape) == 3:
        gray = cv2.cvtColor(reference_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = reference_image

    # Find non-zero pixels (actual content)
    non_zero = cv2.findNonZero(gray)
    x, y, w, h = cv2.boundingRect(non_zero)

    return x, y, w, h


def align_images(reference_image, edited_image):
    """
    Align the edited image with the reference image using feature matching.
    This ensures proper cropping even if the edited image is slightly misaligned.

    Args:
        reference_image: The unedited reference image
        edited_image: The edited image that needs to be cropped

    Returns:
        numpy.ndarray: Aligned edited image
    """
    # Convert reference and edit to grayscale
    reference_grayscale = cv2.cvtColor(reference_image, cv2.COLOR_BGR2GRAY)
    edit_grayscale = cv2.cvtColor(edited_image, cv2.COLOR_BGR2GRAY)

    # Initialize Scale-Invariant Feature Transform detector
    sift = cv2.SIFT_create()

    # Find key points and descriptors
    key_point1, descriptor1 = sift.detectAndCompute(reference_grayscale, None)
    key_point2, descriptor2 = sift.detectAndCompute(edit_grayscale, None)

    # FLANN parameters
    FLANN_INDEX_KDTREE = 1
    index_parameters = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_parameters = dict(checks=50)
    flann = cv2.FlannBasedMatcher(index_parameters, search_parameters)
    matches = flann.knnMatch(descriptor1, descriptor2, k=2)

    # Apply ratio test
    good_matches = []
    for match, n in matches:
        if match.distance < 0.7 * n.distance:
            good_matches.append(match)

    # Get matched key points
    source_points = np.float32([key_point1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    destination_points = np.float32([key_point2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    # Find homography and mask
    homography, mask = cv2.findHomography(destination_points, source_points, cv2.RANSAC, 5.0)

    # Warp edited image
    aligned_image = cv2.warpPerspective(
        edited_image, homography, (reference_image.shape[1], reference_image.shape[0])
    )

    return aligned_image


def crop_edited_image(reference_path, edited_path, output_path):
    """
    Main function to crop the edited image based on the reference image frame.

    Args:
        reference_path: Path to the unedited reference image
        edited_path: Path to the edited image that needs to be cropped
        output_path: Path where the cropped image will be saved
    """
    # CV open and read images
    reference_image = cv2.imread(reference_path)
    edited_image = cv2.imread(edited_path)

    if reference_image is None or edited_image is None:
        raise ValueError("Failed to load one or both images")

    # Align images
    aligned_edited = align_images(reference_image, edited_image)

    # Find the bounds of the reference image
    x, y, w, h = find_frame_bounds(reference_image)

    # Create a mask of the same size as the reference image
    mask = np.zeros(reference_image.shape[:2], dtype=np.uint8)
    mask[y : y + h, x : x + w] = 255

    # Apply the mask to the aligned edited image
    result = cv2.bitwise_and(aligned_edited, aligned_edited, mask=mask)

    # Crop to the content bounds
    cropped_image = result[y : y + h, x : x + w]

    # Save the result
    cv2.imwrite(output_path, cropped_image)

    return cropped_image


def convert_media_path_to_map(path):
    """
    Converts a SG field path if the SG_MEDIA_PATH_MAP is not empty
    Uses os.path.normpath for safe path normalization.

    Args:
        path: (str) Input path string to convert

    Returns:
        (str) Converted path string for the current operating system
    """
    # Check if global is defined
    if SG_MEDIA_PATH_MAP:
        path_map = SG_MEDIA_PATH_MAP

        current_os = platform.system()

        # Normalize the path using os.path.normpath
        path = os.path.normpath(path)

        # Get all possible paths for pattern matching
        all_paths = []
        for os_paths in path_map.values():
            all_paths.extend(os_paths)

        # Try to find a matching pattern
        for index, source_path in enumerate(all_paths):
            normalized_source = os.path.normpath(source_path)
            pattern = re.compile(f"^{re.escape(normalized_source)}", re.IGNORECASE)

            if pattern.match(path):
                # Calculate target index based on position in original lists
                target_idx = index % len(path_map[current_os])
                # Get replacement path for current OS
                replacement = path_map[current_os][target_idx]
                # Replace matched portion with new path
                converted = pattern.sub(replacement, path)
                # Final normalization of the complete path
                return os.path.normpath(converted)
        raise Exception(
            "Error: fn_globals.py:SG_MEDIA_PATH_MAP set to unsupported OS for path substitution"
        )
    else:
        return path


def find_dict_with_value(data, target_value):
    """Find dictionary containing a value in a deeply nested dictionary

    Args:
        data (dict): dictionary to search
        target_value (str or int): value to return

    Returns:
        (dict) the nested dictionary that contains the requested value
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if value == target_value:
                return data
            if isinstance(value, (dict, list)):
                result = find_dict_with_value(value, target_value)
                if result:
                    return result
    elif isinstance(data, list):
        for item in data:
            result = find_dict_with_value(item, target_value)
            if result:
                return result
    return None


def find_path_to_value(data, target_value, current_path=None):
    """Find a index and key path to a value in a deeply nested dictionary.
    Used to find paths in complex Sg data dictionaries

    Args:
        data (dict): dictionary to search
        target_value (str or int): value to return
        current_path (None or List, optional): Used to iteratively assemble path
        on repeat function calls. Defaults to None.

    Returns:
        list: list of indexes and keys to retrieve a dictionary value
    """
    if current_path is None:
        current_path = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = current_path + [key]
            if value == target_value:
                return new_path
            if isinstance(value, (dict, list)):
                result = find_path_to_value(value, target_value, new_path)
                if result:
                    return result
    elif isinstance(data, list):
        for index, item in enumerate(data):
            new_path = current_path + [index]
            result = find_path_to_value(item, target_value, new_path)
            if result:
                return result
    return None


def get_sorted_values(dictionary_list, sort_key="sg_sort_order", value_key=None):
    """Get a sorted list of dictionaries

    Args:
        dictionary_list (list): of dict to sort
        sort_key (str, optional): str of key to sort by . Defaults to "sg_sort_order".
        value_key (any, optional): Defaults to None.

    Returns:
        (list): of ordered dict
    """
    if not dictionary_list:
        return []
    # Sort the list of dictionaries based on the sort_key
    sorted_dictionaries = sorted(dictionary_list, key=lambda x: x[sort_key])

    # Return the values of the specified value_key in the sorted order
    return [dictionary[value_key] if value_key else dictionary for dictionary in sorted_dictionaries]


def filter_versions_ids(entities):
    """Retrieve a unique isolated list of versions from list of SG manifest entities

    Args:
        entities (list): of SG manifest entities

    Returns:
        (list): of int unique version ids
    """
    version_ids = []
    for entity in entities:
        if entity.get("versions"):
            version_ids.extend([x["id"] for x in entity["versions"]])
        if entity.get("cut_items"):
            version_ids.extend([x["version"]["id"] for x in entity["cut_items"]])

        if entity.get("type") == "Version":
            version_ids.append(entity["id"])

    return list(set(version_ids))
