import subprocess
from pathlib import Path


def run_perl(et, font, basedir, scriptfile, pngfile):
    try:
        ploticus_path = subprocess.check_output(['which',
                                                 'ploticus']).decode().strip()
    except subprocess.CalledProcessError:
        print("Ploticus not found.")
        return None
    command = ["/usr/bin/perl", et, "-P", ploticus_path, "-f",
               font or 'ascii', "-T", basedir, "-i", scriptfile]
    err = subprocess.run(command).returncode
    if err != 0:
        return None
    if Path(pngfile).exists():
        return pngfile

    return None