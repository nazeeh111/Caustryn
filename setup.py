# SPDX-License-Identifier: MIT
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildResources(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        target = Path(self.build_lib) / "phaseglass" / "assets"
        for name in ("studio", "examples"):
            shutil.copytree(
                root / name,
                target / name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(root / name, target / name)


setup(cmdclass={"build_py": BuildResources})
