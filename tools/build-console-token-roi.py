#!/usr/bin/env python3
"""Build the optional, local-only research observer extension. No installation."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sysconfig

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','pygobject-3.0','spice-client-gtk-3.0'],text=True))
source=Path(__file__).with_name('console-token-roi.c').resolve()
command=['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-missing-field-initializers',
         '-I'+sysconfig.get_paths()['include'],str(source),'-o',str(a.output/('console_token_roi'+sysconfig.get_config_var('EXT_SUFFIX'))),*flags]
(a.output/'command.json').write_text(json.dumps(command,indent=2)+'\n')
subprocess.run(command,check=True)
