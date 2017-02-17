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

import functools

from heat.tests.convergence.framework import reality
from heat.tests.convergence.framework import scenario_template

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


def verify(test, reality, tmpl):
    LOG.info('Verifying %s', tmpl)

    for name in tmpl.resources:
        rsrc_count = len(reality.resources_by_logical_name(name))
        test.assertEqual(1, rsrc_count,
                         'Found %d copies of resource "%s"' % (rsrc_count,
                                                               name))

    all_rsrcs = reality.all_resources()

    for name, defn in tmpl.resources.items():
        phys_rsrc = reality.resources_by_logical_name(name)[0]

        for prop_name, prop_def in defn.properties.items():
            real_value = reality.resource_properties(phys_rsrc, prop_name)

            if isinstance(prop_def, scenario_template.GetAtt):
                targs = reality.resources_by_logical_name(prop_def.target_name)
                prop_def = targs[0].rsrc_prop_data.data[prop_def.attr]
            elif isinstance(prop_def, scenario_template.GetRes):
                targs = reality.resources_by_logical_name(prop_def.target_name)
                prop_def = targs[0].physical_resource_id
            test.assertEqual(prop_def, real_value,
                             'Unexpected value for %s prop %s' % (name,
                                                                  prop_name))

        len_rsrc_prop_data = 0
        if phys_rsrc.rsrc_prop_data:
            len_rsrc_prop_data = len(phys_rsrc.rsrc_prop_data.data)
        test.assertEqual(len(defn.properties),
                         len_rsrc_prop_data)

    test.assertEqual(set(tmpl.resources), set(r.name for r in all_rsrcs))


def scenario_globals(procs, testcase):
    return {
        'test': testcase,
        'reality': reality.reality,
        'verify': functools.partial(verify,
                                    testcase,
                                    reality.reality),

        'Template': scenario_template.Template,
        'RsrcDef': scenario_template.RsrcDef,
        'GetRes': scenario_template.GetRes,
        'GetAtt': scenario_template.GetAtt,

        'engine': procs.engine,
        'worker': procs.worker,
    }
