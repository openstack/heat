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

import collections

from oslo_config import cfg
from oslo_serialization import jsonutils
import six
import yaml

from heat.common import exception
from heat.common.i18n import _

if hasattr(yaml, 'CSafeLoader'):
    _yaml_loader_base = yaml.CSafeLoader
else:
    _yaml_loader_base = yaml.SafeLoader


class yaml_loader(_yaml_loader_base):
    def _construct_yaml_str(self, node):
        # Override the default string handling function
        # to always return unicode objects
        return self.construct_scalar(node)


if hasattr(yaml, 'CSafeDumper'):
    _yaml_dumper_base = yaml.CSafeDumper
else:
    _yaml_dumper_base = yaml.SafeDumper


class yaml_dumper(_yaml_dumper_base):
    def represent_ordered_dict(self, data):
        return self.represent_dict(data.items())


yaml_loader.add_constructor(u'tag:yaml.org,2002:str',
                            yaml_loader._construct_yaml_str)
# Unquoted dates like 2013-05-23 in yaml files get loaded as objects of type
# datetime.data which causes problems in API layer when being processed by
# openstack.common.jsonutils. Therefore, make unicode string out of timestamps
# until jsonutils can handle dates.
yaml_loader.add_constructor(u'tag:yaml.org,2002:timestamp',
                            yaml_loader._construct_yaml_str)

yaml_dumper.add_representer(collections.OrderedDict,
                            yaml_dumper.represent_ordered_dict)


def simple_parse(tmpl_str, tmpl_url=None):
    try:
        tpl = jsonutils.loads(tmpl_str)
    except ValueError:
        try:
            tpl = yaml.load(tmpl_str, Loader=yaml_loader)
        except yaml.YAMLError:
            # NOTE(prazumovsky): we need to return more informative error for
            # user, so use SafeLoader, which return error message with template
            # snippet where error has been occurred.
            try:
                tpl = yaml.load(tmpl_str, Loader=yaml.SafeLoader)
            except yaml.YAMLError as yea:
                if tmpl_url is None:
                    tmpl_url = '[root stack]'
                yea = six.text_type(yea)
                msg = _('Error parsing template %(tmpl)s '
                        '%(yea)s') % {'tmpl': tmpl_url, 'yea': yea}
                raise ValueError(msg)
        else:
            if tpl is None:
                tpl = {}

    if not isinstance(tpl, dict):
        raise ValueError(_('The template is not a JSON object '
                           'or YAML mapping.'))

    return tpl


def validate_template_limit(contain_str):
    """Validate limit for the template.

    Check if the contain exceeds allowed size range.
    """

    if len(contain_str) > cfg.CONF.max_template_size:
        msg = _("Template size (%(actual_len)s bytes) exceeds maximum "
                "allowed size (%(limit)s bytes)."
                ) % {'actual_len': len(contain_str),
                     'limit': cfg.CONF.max_template_size}
        raise exception.RequestLimitExceeded(message=msg)


def parse(tmpl_str, tmpl_url=None):
    """Takes a string and returns a dict containing the parsed structure.

    This includes determination of whether the string is using the
    JSON or YAML format.
    """

    # TODO(ricolin): Move this validation to api side.
    # Validate nested stack template.
    validate_template_limit(six.text_type(tmpl_str))

    tpl = simple_parse(tmpl_str, tmpl_url)
    # Looking for supported version keys in the loaded template
    if not ('HeatTemplateFormatVersion' in tpl
            or 'heat_template_version' in tpl
            or 'AWSTemplateFormatVersion' in tpl):
        raise ValueError(_("Template format version not found."))
    return tpl


def convert_json_to_yaml(json_str):
    """Convert AWS JSON template format to Heat YAML format.

    :param json_str: a string containing the AWS JSON template format.
    :returns: the equivalent string containing the Heat YAML format.
    """

    # parse the string as json to a python structure
    tpl = jsonutils.loads(json_str, object_pairs_hook=collections.OrderedDict)

    # Replace AWS format version with Heat format version
    def top_level_items(tpl):
        yield ("HeatTemplateFormatVersion", '2012-12-12')

        for k, v in six.iteritems(tpl):
            if k != 'AWSTemplateFormatVersion':
                yield k, v

    # dump python structure to yaml
    return yaml.dump(collections.OrderedDict(top_level_items(tpl)),
                     Dumper=yaml_dumper)
