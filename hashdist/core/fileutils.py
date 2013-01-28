import os
import errno
import shutil
import gzip

def silent_makedirs(path):
    """like os.makedirs, but does not raise error in the event that the directory already exists"""
    try:
        os.makedirs(path)
    except OSError, e:
        if e.errno != errno.EEXIST:
            raise

def silent_unlink(path):
    """like os.unlink but does not raise error if the file does not exist"""
    try:
        os.unlink(path)
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise

def rmtree_up_to(path, parent, silent=False):
    """Executes ``shutil.rmtree(path, ignore_errors=True)``,
    and then removes any empty parent directories
    up until (and excluding) parent.
    """
    path = os.path.realpath(path)
    parent = os.path.realpath(parent)
    if path == parent:
        return
    if not path.startswith(parent):
        raise ValueError('must have path.startswith(parent)')
    shutil.rmtree(path, ignore_errors=True)
    while path != parent:
        path, child = os.path.split(path)
        if path == parent:
            break
        try:
            os.rmdir(path)
        except OSError, e:
            if e.errno != errno.ENOTEMPTY:
                raise
            break

def gzip_compress(source_filename, dest_filename):
    chunk_size = 16 * 1024
    with file(source_filename, 'rb') as src:
        with gzip.open(dest_filename, 'wb') as dst:
            while True:
                chunk = src.read(chunk_size)
                if not chunk: break
                dst.write(chunk)

def atomic_symlink(source, dest):
    """Overwrites a destination symlink atomically without raising error
    if target exists (by first creating link to `source`, then renaming it to `dest`)
    """
    # create-&-rename in order to force-create symlink
    i = 0
    while True:
        try:
            templink = dest + '-%d' % i
            os.symlink(source, templink)
        except OSError, e:
            if e.errno == errno.EEXIST:
                i += 1
            else:
                raise
        else:
            break
    try:
        os.rename(templink, dest)
    except:
        os.unlink(templink)
        raise
