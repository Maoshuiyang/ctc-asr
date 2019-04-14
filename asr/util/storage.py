"""Storage and version control helper methods."""

import hashlib
import os
import shutil
import tarfile
import time

import tensorflow as tf
from git import Repo


def git_revision_hash():
    """Return the git revision id/hash.

    Returns:
        str: Git revision hash.
    """
    repo = Repo('.', search_parent_directories=True)
    return repo.head.object.hexsha


def git_branch():
    """Return the active git branches name.

    Returns:
        str: Git branch.
    """
    repo = Repo('.', search_parent_directories=True)
    try:
        branch_name = repo.active_branch.name
    except TypeError:
        branch_name = 'DETACHED HEAD'
    return branch_name


def git_latest_tag():
    """Return the latest added git tag.

    Returns:
        str: Git tag.
    """
    repo = Repo('.', search_parent_directories=True)
    tags = sorted(repo.tags, key=lambda t: t.commit.committed_datetime)
    return tags[-1].name


def delete_file_if_exists(path):
    """Delete the file for the given path, if it exists.

    Args:
        path (str): File path.

    Returns:
        Nothing.
    """
    if os.path.exists(path) and os.path.isfile(path):
        for i in range(5):
            try:
                os.remove(path)
                break
            except (OSError, ValueError) as exception:
                print('WARN: Error deleting ({}/5) file: {}'.format(i, path))
                if i == 4:
                    raise RuntimeError(path) from exception
                time.sleep(1)


def delete_directory_if_exists(path):
    """Recursive delete of a folder and all contained files.

    Args:
        path (str):  Directory path.

    Returns:
        Nothing.
    """

    if os.path.exists(path) and os.path.isdir(path):
        # https://docs.python.org/3/library/shutil.html#shutil.rmtree
        # Doesn't state which errors are possible.
        try:
            shutil.rmtree(path)
        except OSError as exception:
            raise exception


def maybe_delete_checkpoints(path, delete):
    """Delete a TensorFlow checkpoint directory if requested and necessary.

    Args:
        path (str):
            Path to directory e.g. `FLAGS.train_dir`.
        delete (bool):
            Whether to delete old checkpoints or not. Should probably correspond to `FLAGS.delete`.

    Returns:
        Nothing.
    """
    if tf.gfile.Exists(path) and delete:
        print('Deleting old checkpoint data from: {}'.format(path))
        tf.gfile.DeleteRecursively(path)
        tf.gfile.MakeDirs(path)
    elif tf.gfile.Exists(path) and not delete:
        print('Found old checkpoint data at: {}'.format(path))
    else:
        print('Starting a new training run in: {}'.format(path))
        tf.gfile.MakeDirs(path)


def md5(file_path):
    """Calculate the md5 checksum of files that do not fit in memory.

    Args:
        file_path (str): Path to file.

    Returns:
        str: md5 checksum.
    """
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as file_handle:
        for chunk in iter(lambda: file_handle.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def tar_extract_all(tar_path, target_path):
    """Extract a TAR archive. Overrides existing files.

    # L8ER: Deprecated: no longer needed in this project and will be removed.

    Args:
        tar_path (str): Path of TAR archive.
        target_path (str): Where to extract the archive.

    Returns:
        Nothing.
    """
    assert os.path.exists(target_path) and os.path.isdir(target_path), 'target_path does not exist.'
    with tarfile.open(tar_path, 'r') as tar:
        for file_ in tar:
            try:
                tar.extract(file_, path=target_path)
            except IOError:
                os.remove(os.path.join(target_path, file_.name))
                tar.extract(file_, path=target_path)
            finally:
                os.chmod(os.path.join(target_path, file_.name), file_.mode)
