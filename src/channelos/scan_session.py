"""A scan's private connection and bounded cached-file metadata batches."""
from __future__ import annotations

from .library import utc_now_text


class ScanSession:
    def __init__(self, library, source, *, batch_size=256):
        self.library, self.source = library, source
        self.batch_size = batch_size
        self.connection = library.connect()
        _, key = library.storage_path(source)
        rows = self.connection.execute('''SELECT a.*,l.path_key,
            l.size_bytes AS location_size_bytes,l.mtime_ns AS location_mtime_ns
            FROM media_locations l JOIN media_assets a ON a.asset_id=l.asset_id
            WHERE l.path_key=? OR (substr(l.path_key,1,?)=? AND substr(l.path_key,?,1) IN ('/','\\'))''',
            (key,len(key),key,len(key)+1)).fetchall()
        self.cached = {str(row['path_key']): (int(row['location_size_bytes']),int(row['location_mtime_ns']),library._asset_from_row(row)) for row in rows}
        self.matched = {}
        self.pending = []
        self.source_text, self.source_key = library.storage_path(source)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.flush()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()

    def cached_asset_for_unchanged_path(self, path):
        text, key = self.library.storage_path(path)
        cached = self.cached.get(key)
        if cached is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        if cached[:2] != (stat.st_size,stat.st_mtime_ns):
            return None
        self.matched[str(path)] = text,key
        return cached[2]

    def mark_seen_cached(self, path, source):
        text,key = self.matched.pop(str(path))
        # Retain the trusted size/mtime fingerprint. A concurrent edit must not
        # acquire a new fingerprint without hashing its changed contents.
        self.pending.append((text,self.source_key,self.source_text,utc_now_text(),key))
        if len(self.pending) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self.pending:
            return
        try:
            self.connection.executemany('''UPDATE media_locations SET path=?,source_root_key=?,
                source_root=?,online=1,last_seen_at=? WHERE path_key=?''', self.pending)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        self.pending.clear()

    def upsert_file(self, *args, **kwargs):
        self.flush()
        try:
            value = self.library.upsert_file(*args, **kwargs, _connection=self.connection)
            self.connection.commit()
            return value
        except Exception:
            self.connection.rollback()
            raise
