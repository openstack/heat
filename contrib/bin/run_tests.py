#!/usr/bin/env python
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import sys

from testrepository import commands

CONTRIB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            os.pardir))
TESTR_PATH = os.path.join(CONTRIB_PATH, ".testrepository")


def _run_testr(*args):
    return commands.run_argv([sys.argv[0]] + list(args),
                             sys.stdin, sys.stdout, sys.stderr)

# initialize the contrib test repository if needed
if not os.path.isdir(TESTR_PATH):
    _run_testr('init', '-d', CONTRIB_PATH)
if not _run_testr('run', '-d', CONTRIB_PATH, '--parallel'):
    cur_dir = os.getcwd()
    os.chdir(CONTRIB_PATH)
    print("Slowest Contrib Tests")
    _run_testr("slowest")
    os.chdir(cur_dir)
else:
    sys.exit(1)
