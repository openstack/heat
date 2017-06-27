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
import re

from oslo_utils import encodeutils
from six.moves.urllib import parse as urlparse

from heat.common.i18n import _


class HeatIdentifier(collections.Mapping):

    FIELDS = (
        TENANT, STACK_NAME, STACK_ID, PATH
    ) = (
        'tenant', 'stack_name', 'stack_id', 'path'
    )
    path_re = re.compile(r'stacks/([^/]+)/([^/]+)(.*)')

    def __init__(self, tenant, stack_name, stack_id, path=''):
        """Initialise a HeatIdentifier.

        Identifier is initialized from a Tenant ID, Stack name, Stack ID
        and optional path. If a path is supplied and it does not begin with
        "/", a "/" will be prepended.
        """
        if path and not path.startswith('/'):
            path = '/' + path

        if '/' in stack_name:
            raise ValueError(_('Stack name may not contain "/"'))

        self.identity = {
            self.TENANT: tenant,
            self.STACK_NAME: stack_name,
            self.STACK_ID: str(stack_id),
            self.PATH: path,
        }

    @classmethod
    def from_arn(cls, arn):
        """Generate a new HeatIdentifier by parsing the supplied ARN."""
        fields = arn.split(':')
        if len(fields) < 6 or fields[0].lower() != 'arn':
            raise ValueError(_('"%s" is not a valid ARN') % arn)

        id_fragment = ':'.join(fields[5:])
        path = cls.path_re.match(id_fragment)

        if fields[1] != 'openstack' or fields[2] != 'heat' or not path:
            raise ValueError(_('"%s" is not a valid Heat ARN') % arn)

        return cls(urlparse.unquote(fields[4]),
                   urlparse.unquote(path.group(1)),
                   urlparse.unquote(path.group(2)),
                   urlparse.unquote(path.group(3)))

    @classmethod
    def from_arn_url(cls, url):
        """Generate a new HeatIdentifier by parsing the supplied URL.

        The URL is expected to contain a valid arn as part of the path.
        """
        # Sanity check the URL
        urlp = urlparse.urlparse(url)
        if (urlp.scheme not in ('http', 'https') or
                not urlp.netloc or not urlp.path):
            raise ValueError(_('"%s" is not a valid URL') % url)

        # Remove any query-string and extract the ARN
        arn_url_prefix = '/arn%3Aopenstack%3Aheat%3A%3A'
        match = re.search(arn_url_prefix, urlp.path, re.IGNORECASE)
        if match is None:
            raise ValueError(_('"%s" is not a valid ARN URL') % url)
        # the +1 is to skip the leading /
        url_arn = urlp.path[match.start() + 1:]
        arn = urlparse.unquote(url_arn)
        return cls.from_arn(arn)

    def arn(self):
        """Return as an ARN.

        Returned in the form:
            arn:openstack:heat::<tenant>:stacks/<stack_name>/<stack_id><path>
        """
        return 'arn:openstack:heat::%s:%s' % (urlparse.quote(self.tenant, ''),
                                              self._tenant_path())

    def arn_url_path(self):
        """Return an ARN quoted correctly for use in a URL."""
        return '/' + urlparse.quote(self.arn())

    def url_path(self):
        """Return a URL-encoded path segment of a URL.

        Returned in the form:
            <tenant>/stacks/<stack_name>/<stack_id><path>
        """
        return '/'.join((urlparse.quote(self.tenant, ''), self._tenant_path()))

    def _tenant_path(self):
        """URL-encoded path segment of a URL within a particular tenant.

        Returned in the form:
            stacks/<stack_name>/<stack_id><path>
        """
        return 'stacks/%s%s' % (self.stack_path(),
                                urlparse.quote(encodeutils.safe_encode(
                                    self.path)))

    def stack_path(self):
        """Return a URL-encoded path segment of a URL without a tenant.

        Returned in the form:
            <stack_name>/<stack_id>
        """
        return '%s/%s' % (urlparse.quote(self.stack_name, ''),
                          urlparse.quote(self.stack_id, ''))

    def _path_components(self):
        """Return a list of the path components."""
        return self.path.lstrip('/').split('/')

    def __getattr__(self, attr):
        """Return a component of the identity when accessed as an attribute."""
        if attr not in self.FIELDS:
            raise AttributeError(_('Unknown attribute "%s"') % attr)

        return self.identity[attr]

    def __getitem__(self, key):
        """Return one of the components of the identity."""
        if key not in self.FIELDS:
            raise KeyError(_('Unknown attribute "%s"') % key)

        return self.identity[key]

    def __len__(self):
        """Return the number of components in an identity."""
        return len(self.FIELDS)

    def __contains__(self, key):
        return key in self.FIELDS

    def __iter__(self):
        return iter(self.FIELDS)

    def __repr__(self):
        return repr(dict(self))


class ResourceIdentifier(HeatIdentifier):
    """An identifier for a resource."""

    RESOURCE_NAME = 'resource_name'

    def __init__(self, tenant, stack_name, stack_id, path,
                 resource_name=None):
        """Initialise a new Resource identifier.

        The identifier is based on the identifier components of
        the owning stack and the resource name.
        """
        if resource_name is not None:
            if '/' in resource_name:
                raise ValueError(_('Resource name may not contain "/"'))
            path = '/'.join([path.rstrip('/'), 'resources', resource_name])
        super(ResourceIdentifier, self).__init__(tenant,
                                                 stack_name,
                                                 stack_id,
                                                 path)

    def __getattr__(self, attr):
        """Return a component of the identity when accessed as an attribute."""

        if attr == self.RESOURCE_NAME:
            return self._path_components()[-1]

        return HeatIdentifier.__getattr__(self, attr)

    def stack(self):
        """Return a HeatIdentifier for the owning stack."""
        return HeatIdentifier(self.tenant, self.stack_name, self.stack_id,
                              '/'.join(self._path_components()[:-2]))


class EventIdentifier(HeatIdentifier):
    """An identifier for an event."""

    (RESOURCE_NAME, EVENT_ID) = (ResourceIdentifier.RESOURCE_NAME, 'event_id')

    def __init__(self, tenant, stack_name, stack_id, path,
                 event_id=None):
        """Initialise a new Event identifier based on components.

        The identifier is based on the identifier components of
        the associated resource and the event ID.
        """
        if event_id is not None:
            path = '/'.join([path.rstrip('/'), 'events', event_id])
        super(EventIdentifier, self).__init__(tenant,
                                              stack_name,
                                              stack_id,
                                              path)

    def __getattr__(self, attr):
        """Return a component of the identity when accessed as an attribute."""

        if attr == self.RESOURCE_NAME:
            return getattr(self.resource(), attr)
        if attr == self.EVENT_ID:
            return self._path_components()[-1]

        return HeatIdentifier.__getattr__(self, attr)

    def resource(self):
        """Return a HeatIdentifier for the owning resource."""
        return ResourceIdentifier(self.tenant, self.stack_name, self.stack_id,
                                  '/'.join(self._path_components()[:-2]))

    def stack(self):
        """Return a HeatIdentifier for the owning stack."""
        return self.resource().stack()
