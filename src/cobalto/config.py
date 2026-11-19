"""The project configuration (cblt.json): loading it over the defaults and the
built-in profiles, picking a profile and building the fields that the
profile's command templates can use."""
import json
import os
import shlex

from .messages import CobaltoError

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(HERE, "lib")              # the COBOL core that ships with the CLI
PROFILES_DIR = os.path.join(HERE, "profiles")    # one file per built-in profile

# What a cblt.json does not say. "lib" defaults to LIB_DIR.
DEFAULTS = {"profile": "gnucobol", "sources": ["src/*.cbl"], "tests": ["tests/*.cblt", "tests/*.cbl"],
            "build": "build", "copybooks": [], "test_prefix": "TST"}


def inline_files(profile, folder):
    """A field written as {"file": NAME} takes the text of that file, searched
    in folder: it is how a profile keeps a long script as a template of its
    own instead of a JSON string."""
    out = {}
    for key, value in profile.items():
        if isinstance(value, dict) and set(value) == {"file"}:
            with open(os.path.join(folder, value["file"]), encoding="utf-8") as fh:
                value = fh.read()
        out[key] = value
    return out


def builtin_profiles():
    profiles = {}
    for name in sorted(os.path.splitext(f)[0] for f in os.listdir(PROFILES_DIR)
                       if f.endswith(".json") and not f.startswith(".")):
        with open(os.path.join(PROFILES_DIR, name + ".json"), encoding="utf-8") as fh:
            profiles[name] = inline_files(json.load(fh), PROFILES_DIR)
    return profiles


def load_config(path, required=True):
    """The project's cblt.json over the defaults. Its "profiles" are added to
    the built-in ones: a profile with the name of a built-in one (or with
    "extends": NAME) only states the fields that change."""
    project = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            project = json.load(fh)
    elif required:
        raise CobaltoError("E103", path=path)
    cfg = dict(DEFAULTS, lib=LIB_DIR)
    cfg.update(project)
    profiles = builtin_profiles()
    for name, own in project.get("profiles", {}).items():
        own = inline_files(own, os.path.dirname(path))
        base = own.pop("extends", name)
        if base != name and base not in profiles:
            raise CobaltoError("E101", profile=base, available=", ".join(profiles))
        profiles[name] = dict(profiles.get(base, {}), **own)
    cfg["profiles"] = profiles
    return cfg


def profile_of(cfg, name=None):
    """(name, profile) of the requested profile, or of the project's default."""
    name = name or cfg["profile"]
    if name not in cfg["profiles"]:
        raise CobaltoError("E101", profile=name, available=", ".join(cfg["profiles"]))
    return name, cfg["profiles"][name]


def copy_dirs_of(cfg):
    """Folders where copybooks are searched: the library and the project's."""
    return [cfg["lib"]] + list(cfg.get("copybooks", []))


def template_fields(cfg, gen):
    """Fields for the "compile", "pre", "run" and "post" templates of a
    profile. The *_rel ones are relative to the build folder, for profiles
    that compile from inside it. Paths are written as shell words: one with
    spaces is quoted; the usual ones are left as they are."""
    build = cfg["build"]
    copy_dirs = list(cfg.get("copybooks", []))

    def quoted(files, start=None):
        return " ".join(shlex.quote(os.path.relpath(f, start) if start else f) for f in files)

    return dict(lib=quoted([cfg["lib"]]), lib_rel=quoted([cfg["lib"]], build),
                build=build, exe=os.path.join(build, "cbltdrv"), driver=gen.driver,
                tests=quoted(gen.tests), sources=quoted(gen.sources),
                tests_rel=quoted(gen.tests, build), sources_rel=quoted(gen.sources, build),
                incl=" ".join("-I " + shlex.quote(d) for d in copy_dirs),
                incl_rel=" ".join("-I " + shlex.quote(os.path.relpath(d, build)) for d in copy_dirs))
