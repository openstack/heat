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


import urllib2
import re
import time

# Default retry timeout (seconds) and sleep-time
VERIFY_TIMEOUT = 300
SLEEP_INTERVAL = 10


class VerifyRetry(object):
    def __init__(self, timeout=VERIFY_TIMEOUT, interval=SLEEP_INTERVAL):
        """
        Decorator to wrap verify operations to retry until timeout
        """
        self.timeout = timeout
        self.interval = interval

    def __call__(self, f):
        def fn(*args, **kwargs):
            elapsed = 0
            result = False
            while elapsed < self.timeout and not result:
                result = f(*args, **kwargs)
                if not result:
                    print "Failed verify, sleeping for %ss (%s/%s)" %\
                        (self.interval, elapsed, self.timeout)
                    time.sleep(self.interval)
                    elapsed += self.interval

            return result

        return fn


class VerifyStack:
    '''
    Class containing helper-functions to prove a stack resource or service
    has been created correctly, e.g by accessing the service and checking
    the result is as expected
    '''

    @VerifyRetry()
    def verify_url(self, url, timeout, regex):

        print "Reading html from %s" % url
        try:
            content = urllib2.urlopen(url).read()
        except:
            return False

        matches = re.findall(regex, content)
        if len(matches):
            print "VERIFY : looks OK!"
            return True
        else:
            return False

    @VerifyRetry()
    def verify_wordpress(self, url, timeout=VERIFY_TIMEOUT):
        '''
        Verify the url provided has a functional wordpress installation
        for now we simply scrape the page and do a regex for an expected
        string
        '''
        WORDPRESS_REGEX = "<p>Welcome to the famous five minute WordPress"

        return self.verify_url(url, timeout, WORDPRESS_REGEX)

    def verify_openshift(self, url, timeout=VERIFY_TIMEOUT):
        OPENSHIFT_REGEX = "<title>Welcome to OpenShift</title>"
        return self.verify_url(url, timeout, OPENSHIFT_REGEX)
