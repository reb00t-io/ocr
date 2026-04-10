import os
import hashlib
import random

class ImageCache:
    def __init__(self, cache_dir=".cache/image_cache", max_entries=10000):
        self.cache_dir = cache_dir
        self.max_entries = max_entries
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_file_path(self, key):
        return os.path.join(self.cache_dir, f"{key}.cache")

    def get(self, key):
        cache_file = self._get_cache_file_path(key)
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return f.read()
        return None

    def add(self, key, value):
        # Save the value in its own file
        cache_file = self._get_cache_file_path(key)
        with open(cache_file, 'w') as f:
            f.write(value)

        # Remove oldest files if the cache exceeds max_entries
        # but only check after around 1000 new entries
        if random.randint(0, 1000) == 0:
            self._enforce_cache_size()

    def _enforce_cache_size(self):
        cache_files = sorted(os.listdir(self.cache_dir), key=lambda f: os.path.getctime(os.path.join(self.cache_dir, f)))
        if len(cache_files) > self.max_entries:
            num_files_to_remove = len(cache_files) - self.max_entries
            for i in range(num_files_to_remove):
                os.remove(os.path.join(self.cache_dir, cache_files[i]))

