"""Unit tests for cobalto.config: cblt.json over the defaults, profiles and template fields."""
import json
import os
import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from support import TempDirTestCase

from cobalto import config
from cobalto.config import copy_dirs_of, load_config, profile_of, template_fields
from cobalto.messages import CobaltoError
from cobalto.model import Generated


class ConfigTestCase(TempDirTestCase):
    def project(self, data):
        """Writes data as the cblt.json of a temporary project and loads it."""
        return load_config(self.write("cblt.json", json.dumps(data)))


class DefaultsTest(ConfigTestCase):
    def test_empty_object_is_a_valid_project_with_the_documented_defaults(self):
        cfg = self.project({})
        self.assertEqual({k: cfg[k] for k in ("profile", "sources", "tests", "build", "copybooks", "test_prefix")},
                         {"profile": "gnucobol", "sources": ["src/*.cbl"],
                          "tests": ["tests/*.cblt", "tests/*.cbl"], "build": "build",
                          "copybooks": [], "test_prefix": "TST"})

    def test_lib_defaults_to_the_core_inside_the_package(self):
        cfg = self.project({})
        self.assertTrue(os.path.isfile(os.path.join(cfg["lib"], "CBLTLIB.cbl")))
        self.assertTrue(os.path.isfile(os.path.join(cfg["lib"], "CBLTCTX.cpy")))

    def test_project_values_replace_the_defaults(self):
        cfg = self.project({"profile": "gnucobol-ibm", "sources": ["cobol/*.cob"], "build": "out", "lib": "vendor/lib"})
        self.assertEqual((cfg["profile"], cfg["sources"], cfg["build"], cfg["lib"]),
                         ("gnucobol-ibm", ["cobol/*.cob"], "out", "vendor/lib"))

    def test_fields_the_project_does_not_state_keep_their_default(self):
        cfg = self.project({"build": "out"})
        self.assertEqual((cfg["tests"], cfg["test_prefix"]), (["tests/*.cblt", "tests/*.cbl"], "TST"))

    def test_other_fields_of_the_project_are_kept(self):
        cfg = self.project({"ai": {"backend": "none"}})
        self.assertEqual(cfg["ai"], {"backend": "none"})

    def test_missing_file_is_error_e103_with_its_path(self):
        missing = os.path.join(self.tmp, "cblt.json")
        with self.assertRaises(CobaltoError) as caught:
            load_config(missing)
        self.assertEqual((caught.exception.code, caught.exception.kw["path"]), ("E103", missing))

    def test_missing_file_that_is_not_required_gives_the_defaults(self):
        cfg = load_config(os.path.join(self.tmp, "cblt.json"), required=False)
        self.assertEqual((cfg["profile"], cfg["build"]), ("gnucobol", "build"))


class BuiltinProfilesTest(ConfigTestCase):
    DOCUMENTED = ("gnucobol", "gnucobol-coverage", "gnucobol-debug", "gnucobol-ibm", "gnucobol-mf",
                  "microfocus", "remote-sim", "vms-vsi-cobol")

    def test_documented_profiles_ship_with_the_cli(self):
        profiles = self.project({})["profiles"]
        for name in self.DOCUMENTED:
            self.assertIn(name, profiles)

    def test_every_builtin_profile_has_a_description_and_says_how_results_come_back(self):
        for name, profile in config.builtin_profiles().items():
            with self.subTest(profile=name):
                self.assertTrue(profile.get("description"))
                self.assertIn(profile.get("results_format"), ("lines", "fixed200"))
                self.assertIn(profile.get("results_org"), ("LINE SEQUENTIAL", "SEQUENTIAL"))

    def test_default_profile_compiles_with_the_documented_fields(self):
        gnucobol = config.builtin_profiles()["gnucobol"]
        for field in ("{lib}", "{incl}", "{exe}", "{driver}", "{tests}", "{sources}"):
            self.assertIn(field, gnucobol["compile"])
        self.assertEqual(gnucobol["run"], "{exe}")

    def test_template_kept_in_a_file_is_loaded_as_text(self):
        remote = config.builtin_profiles()["remote-sim"]
        with open(os.path.join(config.PROFILES_DIR, "remote-sim.build.sh"), encoding="utf-8") as fh:
            self.assertEqual(remote["compile"], fh.read())
        self.assertIsInstance(remote["run"], str)

    def test_object_fields_that_are_not_file_references_are_left_alone(self):
        self.assertEqual(config.builtin_profiles()["remote-sim"]["scripts"],
                         {"compile": "CBLT_BUILD.SH", "run": "CBLT_RUN.SH"})


class ProjectProfilesTest(ConfigTestCase):
    def test_profile_named_like_a_builtin_changes_only_the_stated_fields(self):
        builtin = config.builtin_profiles()["gnucobol"]
        cfg = self.project({"profiles": {"gnucobol": {"run": "timeout 60 {exe}"}}})
        changed = cfg["profiles"]["gnucobol"]
        self.assertEqual(changed["run"], "timeout 60 {exe}")
        self.assertEqual({k: v for k, v in changed.items() if k != "run"},
                         {k: v for k, v in builtin.items() if k != "run"})

    def test_overriding_one_profile_leaves_the_others_as_shipped(self):
        cfg = self.project({"profiles": {"gnucobol": {"run": "timeout 60 {exe}"}}})
        self.assertEqual(cfg["profiles"]["gnucobol-ibm"], config.builtin_profiles()["gnucobol-ibm"])

    def test_override_does_not_leak_into_the_next_load(self):
        self.project({"profiles": {"gnucobol": {"run": "timeout 60 {exe}"}}})
        self.assertEqual(self.project({})["profiles"]["gnucobol"]["run"], "{exe}")

    def test_extends_starts_from_another_profile(self):
        builtin = config.builtin_profiles()["gnucobol"]
        cfg = self.project({"profiles": {"strict": {"extends": "gnucobol", "description": "Strict build",
                                                     "error_regex": "^(.+):(\\d+): error"}}})
        strict = cfg["profiles"]["strict"]
        self.assertEqual((strict["description"], strict["error_regex"]), ("Strict build", "^(.+):(\\d+): error"))
        self.assertEqual((strict["compile"], strict["run"]), (builtin["compile"], builtin["run"]))

    def test_extends_is_not_a_field_of_the_resulting_profile(self):
        cfg = self.project({"profiles": {"strict": {"extends": "gnucobol"}}})
        self.assertNotIn("extends", cfg["profiles"]["strict"])

    def test_extended_profile_is_added_and_the_base_is_untouched(self):
        cfg = self.project({"profiles": {"strict": {"extends": "gnucobol", "run": "strict {exe}"}}})
        self.assertEqual(cfg["profiles"]["gnucobol"]["run"], "{exe}")

    def test_extends_of_an_unknown_profile_is_error_e101(self):
        with self.assertRaises(CobaltoError) as caught:
            self.project({"profiles": {"strict": {"extends": "no-such-profile"}}})
        err = caught.exception
        self.assertEqual((err.code, err.kw["profile"]), ("E101", "no-such-profile"))
        self.assertIn("gnucobol", err.kw["available"])

    def test_new_profile_without_extends_has_only_its_own_fields(self):
        own = {"description": "Site compiler", "compile": "sitecc {tests} {sources}", "run": "{exe}"}
        cfg = self.project({"profiles": {"site": own}})
        self.assertEqual(cfg["profiles"]["site"], own)

    def test_template_file_of_a_project_profile_is_read_from_the_project_folder(self):
        self.write("site.build.sh", "#!/bin/sh\nsitecc {tests}\n")
        cfg = self.project({"profiles": {"site": {"compile": {"file": "site.build.sh"}, "run": "{exe}"}}})
        self.assertEqual(cfg["profiles"]["site"]["compile"], "#!/bin/sh\nsitecc {tests}\n")

    def test_template_file_can_replace_a_field_of_an_extended_profile(self):
        self.write("site.run.sh", "exec {exe}\n")
        cfg = self.project({"profiles": {"site": {"extends": "remote-sim", "run": {"file": "site.run.sh"}}}})
        self.assertEqual(cfg["profiles"]["site"]["run"], "exec {exe}\n")
        self.assertEqual(cfg["profiles"]["site"]["compile"], config.builtin_profiles()["remote-sim"]["compile"])


class ProfileOfTest(ConfigTestCase):
    def test_default_profile_of_the_project(self):
        cfg = self.project({"profile": "gnucobol-mf"})
        name, profile = profile_of(cfg)
        self.assertEqual((name, profile), ("gnucobol-mf", cfg["profiles"]["gnucobol-mf"]))

    def test_requested_profile_wins_over_the_default(self):
        cfg = self.project({"profile": "gnucobol-mf"})
        self.assertEqual(profile_of(cfg, "gnucobol-ibm")[0], "gnucobol-ibm")

    def test_unknown_profile_is_error_e101_that_lists_the_available_ones(self):
        cfg = self.project({"profiles": {"site": {"run": "{exe}"}}})
        with self.assertRaises(CobaltoError) as caught:
            profile_of(cfg, "no-such-profile")
        err = caught.exception
        self.assertEqual((err.code, err.kw["profile"]), ("E101", "no-such-profile"))
        self.assertIn("site", err.kw["available"].split(", "))
        self.assertIn("gnucobol", err.kw["available"].split(", "))

    def test_default_profile_that_does_not_exist_is_error_e101(self):
        cfg = self.project({"profile": "typo"})
        with self.assertRaises(CobaltoError) as caught:
            profile_of(cfg)
        self.assertEqual(caught.exception.code, "E101")


class CopyDirsTest(ConfigTestCase):
    def test_library_first_then_the_copybook_folders_of_the_project(self):
        cfg = self.project({"copybooks": ["src", "copy"]})
        self.assertEqual(copy_dirs_of(cfg), [cfg["lib"], "src", "copy"])

    def test_project_without_copybooks_searches_only_the_library(self):
        cfg = self.project({})
        self.assertEqual(copy_dirs_of(cfg), [cfg["lib"]])


class TemplateFieldsTest(ConfigTestCase):
    def fields(self, project=None, **generated):
        cfg = self.project(dict({"lib": "lib"}, **(project or {})))
        gen = Generated(driver=os.path.join("build", "cbltdrv.cbl"), **generated)
        return template_fields(cfg, gen)

    def test_fields_documented_for_the_command_templates(self):
        self.assertEqual(sorted(self.fields()),
                         sorted(["lib", "lib_rel", "build", "exe", "driver", "tests", "sources",
                                 "tests_rel", "sources_rel", "incl", "incl_rel"]))

    def test_build_folder_executable_and_driver(self):
        f = self.fields()
        self.assertEqual((f["build"], f["exe"], f["driver"]),
                         ("build", os.path.join("build", "cbltdrv"), os.path.join("build", "cbltdrv.cbl")))

    def test_tests_are_the_generated_suites_followed_by_the_hand_written_ones(self):
        f = self.fields(gen_files=["build/TSTONE.cbl", "build/TSTTWO.cbl"], legacy_files=["tests/TSTOLD.cbl"])
        self.assertEqual(f["tests"], "build/TSTONE.cbl build/TSTTWO.cbl tests/TSTOLD.cbl")

    def test_sources_are_joined_by_spaces(self):
        self.assertEqual(self.fields(sources=["src/ONE.cbl", "src/TWO.cbl"])["sources"], "src/ONE.cbl src/TWO.cbl")

    def test_path_with_spaces_is_quoted_as_one_shell_word(self):
        f = self.fields(sources=["my src/ONE PROG.cbl", "src/TWO.cbl"])
        self.assertEqual(f["sources"], "'my src/ONE PROG.cbl' src/TWO.cbl")

    def test_library_path_with_spaces_is_quoted(self):
        self.assertEqual(self.fields({"lib": "vendor lib/cobol"})["lib"], "'vendor lib/cobol'")

    def test_usual_paths_are_left_as_they_are(self):
        f = self.fields(sources=["src/ONE-A_1.cbl"])
        self.assertEqual((f["sources"], f["lib"]), ("src/ONE-A_1.cbl", "lib"))

    def test_rel_fields_are_relative_to_the_build_folder(self):
        f = self.fields(gen_files=["build/TSTONE.cbl"], sources=["src/ONE.cbl"])
        self.assertEqual((f["tests_rel"], f["sources_rel"], f["lib_rel"]),
                         ("TSTONE.cbl", os.path.join("..", "src", "ONE.cbl"), os.path.join("..", "lib")))

    def test_rel_path_with_spaces_is_quoted(self):
        f = self.fields(sources=["my src/ONE.cbl"])
        self.assertEqual(f["sources_rel"], "'" + os.path.join("..", "my src", "ONE.cbl") + "'")

    def test_incl_has_one_option_per_copybook_folder(self):
        f = self.fields({"copybooks": ["src", "copy"]})
        self.assertEqual(f["incl"], "-I src -I copy")
        self.assertEqual(f["incl_rel"], "-I " + os.path.join("..", "src") + " -I " + os.path.join("..", "copy"))

    def test_copybook_folder_with_spaces_is_quoted(self):
        f = self.fields({"copybooks": ["copy books"]})
        self.assertEqual(f["incl"], "-I 'copy books'")
        self.assertEqual(f["incl_rel"], "-I '" + os.path.join("..", "copy books") + "'")

    def test_project_without_copybooks_has_empty_incl(self):
        f = self.fields()
        self.assertEqual((f["incl"], f["incl_rel"]), ("", ""))

    def test_fields_fill_the_templates_of_every_builtin_local_profile(self):
        f = self.fields({"copybooks": ["src"]}, gen_files=["build/TSTONE.cbl"], sources=["src/ONE.cbl"])
        for name, profile in config.builtin_profiles().items():
            if "remote" in profile:
                continue        # remote profiles are filled with the fields of cobalto.remote
            with self.subTest(profile=name):
                command = profile["compile"].format(**f)
                self.assertIn("TSTONE.cbl", command)
                self.assertIn("ONE.cbl", command)


if __name__ == "__main__":
    unittest.main()
