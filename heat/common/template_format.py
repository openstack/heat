# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import re
import yaml
import json

from oslo.config import cfg

from heat.common import exception

cfg.CONF.import_opt('max_template_size', 'heat.common.config')

HEAT_VERSIONS = (u'2012-12-12',)
CFN_VERSIONS = (u'2010-09-09',)

if hasattr(yaml, 'CSafeLoader'):
    yaml_loader = yaml.CSafeLoader
else:
    yaml_loader = yaml.SafeLoader

if hasattr(yaml, 'CSafeDumper'):
    yaml_dumper = yaml.CSafeDumper
else:
    yaml_dumper = yaml.SafeDumper


def _construct_yaml_str(self, node):
    # Override the default string handling function
    # to always return unicode objects
    return self.construct_scalar(node)
yaml_loader.add_constructor(u'tag:yaml.org,2002:str', _construct_yaml_str)
# Unquoted dates like 2013-05-23 in yaml files get loaded as objects of type
# datetime.data which causes problems in API layer when being processed by
# openstack.common.jsonutils. Therefore, make unicode string out of timestamps
# until jsonutils can handle dates.
yaml_loader.add_constructor(u'tag:yaml.org,2002:timestamp',
                            _construct_yaml_str)
yaml_loader.add_constructor(u'tag:yaml.org,2002:timestamp',
                            _construct_yaml_str)


def parse(tmpl_str):
    '''
    Takes a string and returns a dict containing the parsed structure.
    This includes determination of whether the string is using the
    JSON or YAML format.
    '''
    if len(tmpl_str) > cfg.CONF.max_template_size:
        msg = _('Template exceeds maximum allowed size.')
        raise exception.RequestLimitExceeded(message=msg)
    if tmpl_str.startswith('{'):
        tpl = json.loads(tmpl_str)
    else:
        try:
            tpl = yaml.load(tmpl_str, Loader=yaml_loader)
        except yaml.YAMLError as yea:
            raise ValueError(yea)
        else:
            if tpl is None:
                tpl = {}
            if u'heat_template_version' not in tpl:
                default_for_missing(tpl, u'HeatTemplateFormatVersion',
                                    HEAT_VERSIONS)
    return tpl


def default_for_missing(tpl, version_param, versions):
    '''
    Checks a parsed template for missing version and sections.

    This is currently only applied to YAML templates.
    '''
    # if version is missing, implicitly use the lastest one
    if version_param not in tpl:
        tpl[version_param] = versions[-1]

    # create empty placeholders for any of the main dict sections
    for param in (u'Parameters', u'Mappings', u'Resources', u'Outputs'):
        if param not in tpl:
            tpl[param] = {}


def convert_json_to_yaml(json_str):
    '''Convert a string containing the AWS JSON template format
    to an equivalent string containing the Heat YAML format.
    '''

    global key_order
    # Replace AWS format version with Heat format version
    json_str = re.sub('"AWSTemplateFormatVersion"\s*:\s*"[^"]+"\s*,',
                      '', json_str)

    # insert a sortable order into the key to preserve file ordering
    key_order = 0

    def order_key(matchobj):
        global key_order
        key = '%s"__%05d__order__%s" :' % (
            matchobj.group(1),
            key_order,
            matchobj.group(2))
        key_order = key_order + 1
        return key
    key_re = re.compile('^(\s*)"([^"]+)"\s*:', re.M)
    json_str = key_re.sub(order_key, json_str)

    # parse the string as json to a python structure
    tpl = yaml.load(json_str, Loader=yaml_loader)

    # dump python structure to yaml
    tpl["HeatTemplateFormatVersion"] = '2012-12-12'
    yml = yaml.dump(tpl, Dumper=yaml_dumper)

    # remove ordering from key names
    yml = re.sub('__\d*__order__', '', yml)
    return yml
