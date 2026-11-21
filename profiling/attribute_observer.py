"""Record the defining class for attributes read by a test on a live instance."""
from collections import defaultdict
from functools import lru_cache, wraps
import json
from pathlib import Path

names = set(json.loads(Path("/profile/attribute-names.json").read_bytes()))
readers = defaultdict(lambda: defaultdict(set))
shared_readers = defaultdict(lambda: defaultdict(set))
shared_scope = None
bases = set()


@lru_cache(maxsize=None)
def declaring_class(cls, name):
    for parent in cls.__mro__:
        if name in parent.__dict__:
            return f"{parent.__module__}:{parent.__qualname__}"
    return ""


def install(classes, active):
    for cls in classes:
        if cls in bases:
            continue
        bases.add(cls)
        install_one(cls, active)


def install_one(cls, active):
    original = cls.__getattribute__

    @wraps(original)
    def read(self, name):
        value = original(self, name)
        if name in names and (test := active()):
            owner = declaring_class(type(self), name)
            if owner:
                readers[name][owner].add(test)
                if shared_scope is not None:
                    shared_readers[name][owner].add(shared_scope)
        return value

    cls.__getattribute__ = read
