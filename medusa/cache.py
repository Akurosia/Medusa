# coding=utf-8
"""Cache (dogpile) used by application."""
from __future__ import unicode_literals

import dbm
import importlib
import logging
import os
from datetime import timedelta

from dogpile.cache.backends.file import AbstractFileLock
from dogpile.cache.region import make_region
from dogpile.util.readwrite_lock import ReadWriteMutex

log = logging.getLogger(__name__)


class MutexLock(AbstractFileLock):
    """:class:`MutexLock` is a thread-based rw lock based on :class:`dogpile.core.ReadWriteMutex`."""

    def __init__(self, filename):
        """Constructor.

        :param filename:
        """
        self.mutex = ReadWriteMutex()

    def acquire_read_lock(self, wait):
        """Default acquire_read_lock."""
        ret = self.mutex.acquire_read_lock(wait)
        return wait or ret

    def acquire_write_lock(self, wait):
        """Default acquire_write_lock."""
        ret = self.mutex.acquire_write_lock(wait)
        return wait or ret

    def release_read_lock(self):
        """Default release_read_lock."""
        return self.mutex.release_read_lock()

    def release_write_lock(self):
        """Default release_write_lock."""
        return self.mutex.release_write_lock()


cache = make_region()
memory_cache = make_region()
recommended_series_cache = make_region()
# Some of the show titles that are used as keys, contain unicode encoded characters. We need to encode them to
# bytestrings to be able to use them as keys in dogpile.
anidb_cache = make_region()


def _remove_dbm_cache(filename):
    """Remove a dbm cache and common companion files."""
    for path in [filename] + [filename + os.extsep + ext for ext in ('db', 'dat', 'pag', 'dir')]:
        if os.path.exists(path):
            os.remove(path)


def _prepare_dbm_cache(filename):
    """Remove dbm cache files that this Python cannot reopen."""
    dbm_type = dbm.whichdb(filename)
    if not dbm_type:
        return

    try:
        importlib.import_module(dbm_type)
    except ImportError:
        log.warning(
            'Removing incompatible dbm cache file %r. '
            'It was created as %r, which is not available in this Python.',
            filename, dbm_type
        )
        _remove_dbm_cache(filename)


def _dbm_arguments(cache_dir, filename):
    cache_file = os.path.join(cache_dir, filename)
    _prepare_dbm_cache(cache_file)
    return {'filename': cache_file, 'lock_factory': MutexLock}


def configure(cache_dir, replace=False):
    """Configure caches."""
    # memory cache
    from subliminal.cache import region as subliminal_cache

    memory_cache.configure('dogpile.cache.memory', expiration_time=timedelta(hours=1))

    # subliminal cache
    subliminal_cache.configure('dogpile.cache.dbm', replace_existing_backend=replace,
                               expiration_time=timedelta(days=30),
                               arguments=_dbm_arguments(cache_dir, 'subliminal.dbm'))

    # application cache
    cache.configure('dogpile.cache.dbm', replace_existing_backend=replace,
                    expiration_time=timedelta(days=1),
                    arguments=_dbm_arguments(cache_dir, 'application.dbm'))

    # recommended series cache
    recommended_series_cache.configure('dogpile.cache.dbm', replace_existing_backend=replace,
                                       expiration_time=timedelta(days=7),
                                       arguments=_dbm_arguments(cache_dir, 'recommended.dbm'))

    # anidb (adba) series cache
    anidb_cache.configure('dogpile.cache.dbm', replace_existing_backend=replace,
                          expiration_time=timedelta(days=3),
                          arguments=_dbm_arguments(cache_dir, 'anidb.dbm'))


def fallback():
    """Memory only configuration. Used for test purposes."""
    from subliminal.cache import region as subliminal_cache
    for region in (cache, memory_cache, subliminal_cache):
        region.configure('dogpile.cache.memory')
