# Copyright 2018 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import subprocess
import tenacity

from paunch.utils import common


class SystemctlException(Exception):
    pass


class SystemctlMaskedException(Exception):
    pass


def systemctl(cmd, log=None, ignore_errors=False):
    log = log or common.configure_logging(__name__)
    if not isinstance(cmd, list):
        raise SystemctlException("systemctl cmd passed must be a list")
    cmd.insert(0, 'systemctl')
    log.debug("Executing: {}".format(" ".join(cmd)))
    r = subprocess.run(cmd,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE,
                       universal_newlines=True)
    if not ignore_errors and r.returncode != 0:
        raise SystemctlException(r.stderr.rstrip())
    return r.stdout.rstrip()


def format_name(name):
    return name if name.endswith('.service') else name + ".service"


def stop(service, log=None):
    systemctl(['stop', service], log)


def daemon_reload(log=None):
    systemctl(['daemon-reload'], log)


def reset_failed(service, log=None):
    systemctl(['reset-failed', service], log)


def is_active(service, log=None):
    try:
        systemctl(['is-active', '-q', service], log)
        return True
    except SystemctlException:
        return False


def is_enabled(service, log=None):
    try:
        systemctl(['is-enabled', '-q', service], log)
        return True
    except SystemctlException:
        return False


def is_masked(service, log=None):
    out = systemctl(['is-enabled', service], log, ignore_errors=True)
    return 'masked' in out


# NOTE(bogdando): this implements a crash-loop with reset-failed
# counters approach that provides an efficient feature parity to the
# classic rate limiting, shall we want to implement that for the
# systemctl command wrapper instead.
@tenacity.retry(  # Retry up to 5 times with jittered exponential backoff
    reraise=True,
    retry=tenacity.retry_if_exception_type(
        SystemctlException
    ),
    wait=tenacity.wait_random_exponential(multiplier=1, max=10),
    stop=tenacity.stop_after_attempt(5)
)
def enable(service, now=True, log=None):
    if is_masked(service, log):
        if log:
            log.warning('Not enabling masked service %s' % service)
        raise SystemctlMaskedException('Service %s is masked' % service)
    cmd = ['enable']
    if now:
        cmd.append('--now')
    cmd.append(service)
    try:
        systemctl(cmd, log)
    except SystemctlException as err:
        # Reset failure counters for the service unit and retry
        reset_failed(service, log)
        raise SystemctlException(str(err))


def disable(service, log=None):
    systemctl(['disable', service], log)


def add_requires(target, units, log=None):
    if is_masked(target, log):
        if log:
            log.debug('Ignoring masked service target %s' % target)
        raise SystemctlMaskedException('Service %s is masked' % target)
    cmd = ['add-requires', target]
    if isinstance(units, list):
        cmd.extend(units)
    else:
        cmd.append(units)
    systemctl(cmd, log)
