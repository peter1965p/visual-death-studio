"""Echte Builds der Web-Vorlagen (npm install + build). Langsam und netzabhängig: nur mit VDS_SLOW_TESTS=1."""
import os
import shutil
import subprocess

import pytest

from vds.projects.templates import BY_ID, create_project

pytestmark = pytest.mark.skipif(os.environ.get("VDS_SLOW_TESTS") != "1" or not shutil.which("npm"), reason="langsam: VDS_SLOW_TESTS=1 setzen (braucht npm und Netzwerk)")


@pytest.mark.parametrize("tid", ["react-vite", "vue-vite", "next", "nuxt", "angular"])
def test_template_installs_and_builds(tid, tmp_path):
    root, main, log = create_project(BY_ID[tid], "Mein App", tmp_path, {"git": False})
    r = subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=root, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-800:]
    r = subprocess.run(["npm", "run", "build"], cwd=root, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
