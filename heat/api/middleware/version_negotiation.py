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

"""Inspects the requested URI for a version string and/or Accept headers.

Also attempts to negotiate an API controller to return.
"""

import re

from oslo_log import log as logging
import webob

from heat.common import wsgi

LOG = logging.getLogger(__name__)


class VersionNegotiationFilter(wsgi.Middleware):

    def __init__(self, version_controller, app, conf, **local_conf):
        self.versions_app = version_controller(conf)
        self.version_uri_regex = re.compile(r"^v(\d+)\.?(\d+)?")
        self.conf = conf
        super(VersionNegotiationFilter, self).__init__(app)

    def process_request(self, req):
        """Process Accept header or simply return correct API controller.

        If there is a version identifier in the URI,
        return the correct API controller, otherwise, if we
        find an Accept: header, process it
        """

        # Make sure the request path is valid UTF-8
        try:
            req.path
        except UnicodeDecodeError:
            return webob.exc.HTTPBadRequest()

        # See if a version identifier is in the URI passed to
        # us already. If so, simply return the right version
        # API controller
        msg = ("Processing request: %(method)s %(path)s Accept: "
               "%(accept)s" % {'method': req.method,
                               'path': req.path, 'accept': req.accept})
        LOG.debug(msg)

        # If the request is for /versions, just return the versions container
        if req.path_info_peek() in ("versions", ""):
            return self.versions_app

        match = self._match_version_string(req.path_info_peek(), req)
        if match:
            major_version = req.environ['api.major_version']
            minor_version = req.environ['api.minor_version']

            if (major_version == 1 and minor_version == 0):
                LOG.debug("Matched versioned URI. "
                          "Version: %(major_version)d.%(minor_version)d"
                          % {'major_version': major_version,
                             'minor_version': minor_version})
                # Strip the version from the path
                req.path_info_pop()
                return None
            else:
                LOG.debug("Unknown version in versioned URI: "
                          "%(major_version)d.%(minor_version)d. "
                          "Returning version choices."
                          % {'major_version': major_version,
                             'minor_version': minor_version})
                return self.versions_app

        accept = str(req.accept)
        if accept.startswith('application/vnd.openstack.orchestration-'):
            token_loc = len('application/vnd.openstack.orchestration-')
            accept_version = accept[token_loc:]
            match = self._match_version_string(accept_version, req)
            if match:
                major_version = req.environ['api.major_version']
                minor_version = req.environ['api.minor_version']
                if (major_version == 1 and minor_version == 0):
                    LOG.debug("Matched versioned media type. Version: "
                              "%(major_version)d.%(minor_version)d"
                              % {'major_version': major_version,
                                 'minor_version': minor_version})
                    return None
                else:
                    LOG.debug("Unknown version in accept header: "
                              "%(major_version)d.%(minor_version)d... "
                              "returning version choices."
                              % {'major_version': major_version,
                                  'minor_version': minor_version})
                    return self.versions_app
        else:
            if req.accept not in ('*/*', ''):
                LOG.debug("Unknown accept header: %s... "
                          "returning HTTP not found.", req.accept)
            return webob.exc.HTTPNotFound()
        return None

    def _match_version_string(self, subject, req):
        """Given a subject, tries to match a major and/or minor version number.

        If found, sets the api.major_version and api.minor_version environ
        variables.

        Returns True if there was a match, false otherwise.

        :param subject: The string to check
        :param req: Webob.Request object
        """
        match = self.version_uri_regex.match(subject)
        if match:
            major_version, minor_version = match.groups(0)
            major_version = int(major_version)
            minor_version = int(minor_version)
            req.environ['api.major_version'] = major_version
            req.environ['api.minor_version'] = minor_version
        return match is not None
