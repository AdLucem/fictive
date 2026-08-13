import importlib
import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class SubmoduleImportTests(unittest.TestCase):
    def test_repo_root_package_reexports_inner_package_api(self):
        package_name = "vendored_fictive"
        created_modules = []

        try:
            spec = importlib.util.spec_from_file_location(
                package_name,
                REPO_ROOT / "__init__.py",
                submodule_search_locations=[str(REPO_ROOT)],
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)

            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            created_modules.append(package_name)
            spec.loader.exec_module(module)

            self.assertTrue(hasattr(module, "Actor"))
            self.assertTrue(hasattr(module, "Interpreter"))
            self.assertTrue(hasattr(module, "load_scenario_config"))

            actors_module = importlib.import_module(f"{package_name}.actors")
            parser_module = importlib.import_module(f"{package_name}.parser")
            commands_module = importlib.import_module(
                f"{package_name}.parser.commands"
            )

            self.assertIs(module.Actor, actors_module.Actor)
            self.assertTrue(hasattr(parser_module, "__path__"))
            self.assertTrue(hasattr(commands_module, "parse_command_dict"))

            created_modules.extend(
                name for name in sys.modules if name.startswith(f"{package_name}.")
            )
        finally:
            for name in sorted(set(created_modules), reverse=True):
                sys.modules.pop(name, None)
