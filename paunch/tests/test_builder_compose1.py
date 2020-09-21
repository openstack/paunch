# -*- coding: utf-8 -*-

# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections
import inspect
import json
import mock
import tenacity

from paunch.builder import compose1
from paunch import runner
from paunch.tests import base


class TestComposeV1Builder(base.TestCase):

    @mock.patch("psutil.Process.cpu_affinity", return_value=[0, 1, 2, 3])
    @mock.patch("paunch.builder.compose1.ComposeV1Builder.delete_updated",
                return_value=False)
    def test_apply(self, mock_delete_updated, mock_cpu):
        orig_call = tenacity.wait.wait_random_exponential.__call__
        orig_argspec = inspect.getargspec(orig_call)
        config = {
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            },
            'two': {
                'start_order': 1,
                'image': 'centos:7',
            },
            'three': {
                'start_order': 2,
                'image': 'centos:6',
            },
            'four': {
                'start_order': 10,
                'image': 'centos:7',
            },
            'four_ls': {
                'action': 'exec',
                'start_order': 20,
                'command': ['four', 'ls', '-l', '/']
            }
        }

        r = runner.DockerRunner(managed_by='tester', docker_cmd='docker')
        exe = mock.Mock()
        exe.side_effect = [
            ('Pulled centos:6', '', 0),  # inspect for image centos:6
            ('Pulled centos:7', 'ouch', 1),  # pull centos:6 fails
            ('Pulled centos:7', '', 0),  # pull centos:6 succeeds
            # container_names for delete_missing
            ('''five five
six six
two two
three-12345678 three''', '', 0),
            ('', '', 0),  # stop five
            ('', '', 0),  # rm five
            ('', '', 0),  # stop six
            ('', '', 0),  # rm six
            # container_names for rename_containers
            ('three-12345678 three', '', 0),
            ('', '', 0),  # rename three
            # desired/container_names to be refreshed after delete/rename
            ('three three', '', 0),  # renamed three already exists
            ('Created one-12345678', '', 0),
            ('Created two-12345678', '', 0),
            ('Created four-12345678', '', 0),
            ('a\nb\nc', '', 0)  # exec four
        ]
        r.discover_container_name = lambda n, c: '%s-12345678' % n
        r.unique_container_name = lambda n: '%s-12345678' % n
        r.execute = exe

        with mock.patch('tenacity.wait.wait_random_exponential.__call__') as f:
            f.return_value = 0
            with mock.patch('inspect.getargspec') as mock_args:
                mock_args.return_value = orig_argspec
                builder = compose1.ComposeV1Builder('foo', config, r)

        stdout, stderr, deploy_status_code = builder.apply()
        self.assertEqual(0, deploy_status_code)
        self.assertEqual([
            'Pulled centos:6',
            'Pulled centos:7',
            'Created one-12345678',
            'Created two-12345678',
            'Created four-12345678',
            'a\nb\nc'
        ], stdout)
        self.assertEqual([], stderr)

        exe.assert_has_calls([
            # Pull image centos:6
            mock.call(
                ['docker', 'pull', 'centos:6'], mock.ANY
            ),
            # first pull attempt fails
            mock.call(
                ['docker', 'pull', 'centos:7'], mock.ANY
            ),
            # second pull attempt succeeds
            mock.call(
                ['docker', 'pull', 'centos:7'], mock.ANY
            ),
            # container_names for delete_missing
            mock.call(
                ['docker', 'ps', '-a',
                 '--filter', 'label=managed_by=tester',
                 '--filter', 'label=config_id=foo',
                 '--format', '{{.Names}} {{.Label "container_name"}}'],
                mock.ANY
            ),
            # rm containers missing in config
            mock.call(['docker', 'stop', 'five'], mock.ANY),
            mock.call(['docker', 'rm', 'five'], mock.ANY),
            mock.call(['docker', 'stop', 'six'], mock.ANY),
            mock.call(['docker', 'rm', 'six'], mock.ANY),
            # container_names for rename
            mock.call(
                ['docker', 'ps', '-a',
                 '--filter', 'label=managed_by=tester',
                 '--format', '{{.Names}} {{.Label "container_name"}}'],
                mock.ANY
            ),
            # rename three from an ephemeral to the static name
            mock.call(['docker', 'rename', 'three-12345678', 'three'],
                      mock.ANY),
            # container_names to be refreshed after delete/rename
            mock.call(
                ['docker', 'ps', '-a',
                 '--filter', 'label=managed_by=tester',
                 '--filter', 'label=config_id=foo',
                 '--format', '{{.Names}} {{.Label "container_name"}}'],
                mock.ANY
            ),
            # run one
            mock.call(
                ['docker', 'run', '--name', 'one-12345678',
                 '--label', 'config_id=foo',
                 '--label', 'container_name=one',
                 '--label', 'managed_by=tester',
                 '--label', 'config_data=%s' % json.dumps(config['one']),
                 '--detach=true', '--cpuset-cpus=0,1,2,3', 'centos:7'],
                mock.ANY
            ),
            # run two
            mock.call(
                ['docker', 'run', '--name', 'two-12345678',
                 '--label', 'config_id=foo',
                 '--label', 'container_name=two',
                 '--label', 'managed_by=tester',
                 '--label', 'config_data=%s' % json.dumps(config['two']),
                 '--detach=true', '--cpuset-cpus=0,1,2,3', 'centos:7'],
                mock.ANY
            ),
            # run four
            mock.call(
                ['docker', 'run', '--name', 'four-12345678',
                 '--label', 'config_id=foo',
                 '--label', 'container_name=four',
                 '--label', 'managed_by=tester',
                 '--label', 'config_data=%s' % json.dumps(config['four']),
                 '--detach=true', '--cpuset-cpus=0,1,2,3', 'centos:7'],
                mock.ANY
            ),
            # execute within four
            mock.call(
                ['docker', 'exec', 'four-12345678', 'ls', '-l', '/'], mock.ANY
            ),
        ])

    @mock.patch("psutil.Process.cpu_affinity", return_value=[0, 1, 2, 3])
    @mock.patch("paunch.runner.DockerRunner.container_names")
    @mock.patch("paunch.runner.DockerRunner.discover_container_name",
                return_value='one')
    def test_apply_idempotency(self, mock_dname, mock_cnames, mock_cpu):
        config = {
            # running with the same config and given an ephemeral name
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            },
            # not running yet
            'two': {
                'start_order': 1,
                'image': 'centos:7',
            },
            # running, but with a different config
            'three': {
                'start_order': 2,
                'image': 'centos:7',
            },
            # not running yet
            'four': {
                'start_order': 10,
                'image': 'centos:7',
            },
            'one_ls': {
                'action': 'exec',
                'start_order': 20,
                'command': ['one', 'ls', '-l', '/']
            }
            # five is running but is not managed by us
        }
        # represents the state before and after renaming/removing things
        mock_cnames.side_effect = (
            # delete_missing
            [['five', 'five'], ['one-12345678', 'one'], ['three', 'three']],
            # rename_containers
            [['one-12345678', 'one']],
            # refresh container_names/desired after del/rename
            [['one', 'one'], ['three', 'three']],
            # refresh container_names/desired after delete_updated
            [['one', 'one']]
        )
        r = runner.DockerRunner(managed_by='tester', docker_cmd='docker')
        exe = mock.Mock()
        exe.side_effect = [
            # inspect for image centos:7
            ('Pulled centos:7', '', 0),
            # stop five
            ('', '', 0),
            # rm five
            ('', '', 0),
            ('', '', 0),  # ps for rename one
            # inspect one
            ('[{"Config": {"Labels": {"config_data": '
             '"{\\\"start_order\\\": 0, \\\"image\\\": \\\"centos:7\\\"}"'
             '}}}]', '', 0),
            ('Created two-12345678', '', 0),
            # inspect three
            ('[{"Config": {"Labels": {"config_data": '
             '"{\\\"start_order\\\": 42, \\\"image\\\": \\\"centos:7\\\"}"'
             '}}}]', '', 0),
            # stop three, changed config data
            ('', '', 0),
            # rm three, changed config data
            ('', '', 0),
            ('Created three-12345678', '', 0),
            ('Created four-12345678', '', 0),
            ('a\nb\nc', '', 0)  # exec one
        ]
        r.discover_container_name = lambda n, c: '%s-12345678' % n
        r.unique_container_name = lambda n: '%s-12345678' % n
        r.execute = exe

        builder = compose1.ComposeV1Builder('foo', config, r)
        stdout, stderr, deploy_status_code = builder.apply()
        self.assertEqual(0, deploy_status_code)
        self.assertEqual([
            'Pulled centos:7',
            'Created two-12345678',
            'Created three-12345678',
            'Created four-12345678',
            'a\nb\nc'
        ], stdout)
        self.assertEqual([], stderr)

        exe.assert_has_calls([
            # pull image centos:7
            mock.call(
                ['docker', 'pull', 'centos:7'], mock.ANY
            ),
            # rm containers not in config
            mock.call(['docker', 'stop', 'five'], mock.ANY),
            mock.call(['docker', 'rm', 'five'], mock.ANY),
            # rename one from an ephemeral to the static name
            mock.call(['docker', 'rename', 'one-12345678', 'one'],
                      mock.ANY),
            # check the renamed one, config hasn't changed
            mock.call(['docker', 'inspect', '--type', 'container',
                       'one'], mock.ANY),
            # don't run one, its already running
            # run two
            mock.call(
                ['docker', 'run', '--name', 'two-12345678',
                 '--label', 'config_id=foo',
                 '--label', 'container_name=two',
                 '--label', 'managed_by=tester',
                 '--label', 'config_data=%s' % json.dumps(config['two']),
                 '--detach=true', '--cpuset-cpus=0,1,2,3',
                 'centos:7'], mock.ANY
            ),
            # rm three, changed config
            mock.call(['docker', 'inspect', '--type', 'container',
                       'three'], mock.ANY),
            mock.call(['docker', 'stop', 'three'], mock.ANY),
            mock.call(['docker', 'rm', 'three'], mock.ANY),
            # run three
            mock.call(
                ['docker', 'run', '--name', 'three-12345678',
                 '--label', 'config_id=foo',
                 '--label', 'container_name=three',
                 '--label', 'managed_by=tester',
                 '--label', 'config_data=%s' % json.dumps(config['three']),
                 '--detach=true', '--cpuset-cpus=0,1,2,3',
                 'centos:7'], mock.ANY
            ),
            # run four
            mock.call(
                ['docker', 'run', '--name', 'four-12345678',
                 '--label', 'config_id=foo',
                 '--label', 'container_name=four',
                 '--label', 'managed_by=tester',
                 '--label', 'config_data=%s' % json.dumps(config['four']),
                 '--detach=true', '--cpuset-cpus=0,1,2,3',
                 'centos:7'], mock.ANY
            ),
            # FIXME(bogdando): shall exec ls in the renamed one!
            # Why discover_container_name is never called to get it as c_name?
            mock.call(
                ['docker', 'exec', 'one-12345678', 'ls', '-l',
                 '/'], mock.ANY
            ),
        ])

    def test_apply_failed_pull(self):
        orig_call = tenacity.wait.wait_random_exponential.__call__
        orig_argspec = inspect.getargspec(orig_call)
        config = {
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            },
            'two': {
                'start_order': 1,
                'image': 'centos:7',
            },
            'three': {
                'start_order': 2,
                'image': 'centos:6',
            },
            'four': {
                'start_order': 10,
                'image': 'centos:7',
            },
            'four_ls': {
                'action': 'exec',
                'start_order': 20,
                'command': ['four', 'ls', '-l', '/']
            }
        }

        r = runner.DockerRunner(managed_by='tester', docker_cmd='docker')
        exe = mock.Mock()
        exe.side_effect = [
            ('Pulled centos:6', '', 0),  # inspect for image centos:6
            ('Pulling centos:7', 'ouch', 1),  # pull centos:7 failure
            ('Pulling centos:7', 'ouch', 1),  # pull centos:7 retry 2
            ('Pulling centos:7', 'ouch', 1),  # pull centos:7 retry 3
            ('Pulling centos:7', 'ouch', 1),  # pull centos:7 retry 4
        ]
        r.execute = exe

        with mock.patch('tenacity.wait.wait_random_exponential.__call__') as f:
            f.return_value = 0
            with mock.patch('inspect.getargspec') as mock_args:
                mock_args.return_value = orig_argspec
                builder = compose1.ComposeV1Builder('foo', config, r)

        stdout, stderr, deploy_status_code = builder.apply()
        self.assertEqual(1, deploy_status_code)
        self.assertEqual(['Pulled centos:6', 'Pulling centos:7'], stdout)
        self.assertEqual(['ouch'], stderr)

        exe.assert_has_calls([
            mock.call(
                ['docker', 'pull', 'centos:6'], mock.ANY
            ),
            mock.call(
                ['docker', 'pull', 'centos:7'], mock.ANY
            ),
        ])

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_label_arguments(self, runner):
        r = runner.return_value
        r.managed_by = 'tester'
        builder = compose1.ComposeV1Builder('foo', {}, r)
        cmd = []
        builder.label_arguments(cmd, 'one')
        self.assertEqual(
            ['--label', 'config_id=foo',
             '--label', 'container_name=one',
             '--label', 'managed_by=tester',
             '--label', 'config_data=null'],
            cmd)

        labels = collections.OrderedDict()
        labels['foo'] = 'bar'
        labels['bar'] = 'baz'

        builder = compose1.ComposeV1Builder('foo', {}, r, labels=labels)
        cmd = []
        builder.label_arguments(cmd, 'one')
        self.assertEqual(
            ['--label', 'foo=bar',
             '--label', 'bar=baz',
             '--label', 'config_id=foo',
             '--label', 'container_name=one',
             '--label', 'managed_by=tester',
             '--label', 'config_data=null'],
            cmd)

    @mock.patch("psutil.Process.cpu_affinity", return_value=[0, 1, 2, 3])
    def test_docker_run_args(self, mock_cpu):
        config = {
            'one': {
                'image': 'centos:7',
                'privileged': True,
                'user': 'bar',
                'net': 'host',
                'ipc': 'host',
                'pid': 'container:bar',
                'uts': 'host',
                'restart': 'always',
                'healthcheck': {
                    'test': '/bin/true',
                    'interval': '30s',
                    'timeout': '10s',
                    'retries': 3
                },
                'env_file': '/tmp/foo.env',
                'log_tag': '{{.ImageName}}/{{.Name}}/{{.ID}}',
                'cpu_shares': 600,
                'security_opt': 'label:disable',
                'cpuset_cpus': 'all',
                'mem_limit': '1G',
                'memswap_limit': '1G',
                'mem_swappiness': '60'
            }
        }
        builder = compose1.ComposeV1Builder('foo', config, None)

        cmd = ['docker', 'run', '--name', 'one']
        builder.docker_run_args(cmd, 'one')
        self.assertEqual(
            ['docker', 'run', '--name', 'one',
             '--detach=true', '--env-file=/tmp/foo.env',
             '--net=host', '--ipc=host', '--pid=container:bar',
             '--uts=host', '--health-cmd=/bin/true', '--health-interval=30s',
             '--health-timeout=10s', '--health-retries=3',
             '--privileged=true', '--restart=always', '--user=bar',
             '--log-opt=tag={{.ImageName}}/{{.Name}}/{{.ID}}',
             '--cpu-shares=600',
             '--security-opt=label:disable',
             '--memory=1G',
             '--memory-swap=1G',
             '--memory-swappiness=60',
             'centos:7'],
            cmd
        )

    @mock.patch("psutil.Process.cpu_affinity", return_value=[0, 1, 2, 3])
    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_docker_run_args_lists(self, mock_runner, mock_cpu):
        config = {
            'one': {
                'image': 'centos:7',
                'detach': False,
                'command': 'ls -l /foo',
                'remove': True,
                'tty': True,
                'interactive': True,
                'environment': ['FOO=BAR', 'BAR=BAZ'],
                'env_file': ['/tmp/foo.env', '/tmp/bar.env'],
                'ulimit': ['nofile=1024', 'nproc=1024'],
                'volumes': ['/foo:/foo:rw', '/bar:/bar:ro'],
                'volumes_from': ['two', 'three']
            }
        }
        mock_runner.validate_volume_source.return_value = True
        builder = compose1.ComposeV1Builder('foo', config, mock_runner)

        cmd = ['docker', 'run', '--name', 'one']
        builder.docker_run_args(cmd, 'one')
        self.assertEqual(
            ['docker', 'run', '--name', 'one',
             '--env-file=/tmp/foo.env', '--env-file=/tmp/bar.env',
             '--env=FOO=BAR', '--env=BAR=BAZ',
             '--rm', '--interactive', '--tty',
             '--ulimit=nofile=1024', '--ulimit=nproc=1024',
             '--volume=/foo:/foo:rw', '--volume=/bar:/bar:ro',
             '--volumes-from=two', '--volumes-from=three',
             '--cpuset-cpus=0,1,2,3',
             'centos:7', 'ls', '-l', '/foo'],
            cmd
        )

    @mock.patch("psutil.Process.cpu_affinity", return_value=[0, 1, 2, 3])
    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_docker_run_args_lists_with_cpu(self, mock_runner, mock_cpu):
        config = {
            'one': {
                'image': 'centos:7',
                'detach': False,
                'command': 'ls -l /foo',
                'remove': True,
                'tty': True,
                'interactive': True,
                'environment': ['FOO=BAR', 'BAR=BAZ'],
                'env_file': ['/tmp/foo.env', '/tmp/bar.env'],
                'ulimit': ['nofile=1024', 'nproc=1024'],
                'volumes': ['/foo:/foo:rw', '/bar:/bar:ro'],
                'volumes_from': ['two', 'three'],
                'cpuset_cpus': '0-2',
            }
        }
        mock_runner.validate_volume_source.return_value = True
        builder = compose1.ComposeV1Builder('foo', config, mock_runner)

        cmd = ['docker', 'run', '--name', 'one']
        builder.docker_run_args(cmd, 'one')
        self.assertEqual(
            ['docker', 'run', '--name', 'one',
             '--env-file=/tmp/foo.env', '--env-file=/tmp/bar.env',
             '--env=FOO=BAR', '--env=BAR=BAZ',
             '--rm', '--interactive', '--tty',
             '--ulimit=nofile=1024', '--ulimit=nproc=1024',
             '--volume=/foo:/foo:rw', '--volume=/bar:/bar:ro',
             '--volumes-from=two', '--volumes-from=three',
             '--cpuset-cpus=0-2',
             'centos:7', 'ls', '-l', '/foo'],
            cmd
        )

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_docker_exec_args(self, runner):
        r = runner.return_value
        r.discover_container_name.return_value = 'one-12345678'
        config = {
            'one': {
                'command': 'ls -l /foo',
                'privileged': True,
                'environment': ['FOO=BAR'],
                'user': 'bar'
            }
        }
        self.builder = compose1.ComposeV1Builder(
            'foo', config, runner.return_value)

        cmd = ['docker', 'exec']
        self.builder.docker_exec_args(cmd, 'one')
        self.assertEqual(
            ['docker', 'exec',
             '--privileged=true', '--user=bar',
             '--env=FOO=BAR',
             'one-12345678', '-l', '/foo'],
            cmd
        )

    def test_command_argument(self):
        b = compose1.ComposeV1Builder
        self.assertEqual([], b.command_argument(None))
        self.assertEqual([], b.command_argument(''))
        self.assertEqual([], b.command_argument([]))
        self.assertEqual(
            ['ls', '-l', '/foo-bar'],
            b.command_argument(['ls', '-l', '/foo-bar'])
        )
        self.assertEqual(
            ['ls', '-l', '/foo-bar'],
            b.command_argument('ls -l /foo-bar')
        )
        self.assertEqual(
            ['ls', '-l', '/foo bar'],
            b.command_argument(['ls', '-l', '/foo bar'])
        )
        # don't expect quoted spaces to do the right thing
        self.assertEqual(
            ['ls', '-l', '"/foo', 'bar"'],
            b.command_argument('ls -l "/foo bar"')
        )

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    @mock.patch("psutil.Process.cpu_affinity", return_value=[0, 1, 2, 3])
    def test_docker_run_args_validation_true(self, mock_cpu, mock_runner):
        config = {
            'one': {
                'image': 'foo',
                'volumes': ['/foo:/foo:rw', '/bar:/bar:ro'],
            }
        }
        mock_runner.validate_volume_source.return_value = True
        builder = compose1.ComposeV1Builder('foo', config, mock_runner)

        cmd = ['docker']
        self.assertTrue(builder.docker_run_args(cmd, 'one'))
        self.assertEqual(
            ['docker', '--detach=true', '--volume=/foo:/foo:rw',
             '--volume=/bar:/bar:ro', '--cpuset-cpus=0,1,2,3', 'foo'],
            cmd
        )

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    @mock.patch("psutil.Process.cpu_affinity", return_value=[0, 1, 2, 3])
    def test_docker_run_args_validation_false(self, mock_cpu, mock_runner):
        config = {
            'one': {
                'image': 'foo',
                'volumes': ['/foo:/foo:rw', '/bar:/bar:ro'],
            }
        }
        mock_runner.validate_volume_source.return_value = False
        builder = compose1.ComposeV1Builder('foo', config, mock_runner)

        cmd = ['docker']
        self.assertFalse(builder.docker_run_args(cmd, 'one'))
        self.assertEqual(
            ['docker', '--detach=true', '--volume=/foo:/foo:rw',
             '--volume=/bar:/bar:ro', '--cpuset-cpus=0,1,2,3', 'foo'],
            cmd
        )

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_delete_updated_no_change(self, runner):
        mock_inspect = mock.MagicMock()
        mock_inspect.side_effect = [
            {
                "Id": ("d038dccebdb0996ed36ab4ff06e7c424b3816d67664aa11e00642"
                       "be5e00cec55"),
                "Config": {
                    "Labels": {
                        "config_data": """{
                            \"start_order\": 0,
                            \"image": \"centos:7\"
                        }"""
                    },
                    "Image": "127.0.0.1:8787/centos:7"
                },
                "Image": "sha256:1"
            },
            "sha256:1"
        ]
        runner.inspect = mock_inspect
        mock_remove = mock.MagicMock()
        runner.remove_container = mock_remove

        config = {
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            }
        }

        self.builder = compose1.ComposeV1Builder(
            'one', config, runner.return_value)

        self.builder.runner = runner
        self.assertFalse(self.builder.delete_updated('one', [['one']]))
        calls = [
            mock.call('one'),
            mock.call('127.0.0.1:8787/centos:7',
                      '{{index .Id}}',
                      type='image')
        ]
        mock_inspect.has_calls(calls)
        mock_remove.assert_not_called()

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_delete_updated_inspect_empty(self, runner):
        mock_inspect = mock.MagicMock()
        mock_inspect.return_value = None
        runner.inspect = mock_inspect
        mock_remove = mock.MagicMock()
        runner.remove_container = mock_remove

        config = {
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            }
        }

        self.builder = compose1.ComposeV1Builder(
            'one', config, runner.return_value)

        self.builder.runner = runner
        self.assertTrue(self.builder.delete_updated('one', [['one']]))
        mock_inspect.assert_called_once_with('one')
        mock_remove.assert_called_once_with('one')

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_delete_updated_no_config_data(self, runner):
        mock_inspect = mock.MagicMock()
        mock_inspect.side_effect = [
            {
                "Id": ("d038dccebdb0996ed36ab4ff06e7c424b3816d67664aa11e00642"
                       "be5e00cec55"),
                "Config": {
                    "Labels": {},
                    "Image": "127.0.0.1:8787/centos:7"
                },
                "Image": "sha256:1"
            },
            "sha256:1"
        ]
        runner.inspect = mock_inspect
        mock_remove = mock.MagicMock()
        runner.remove_container = mock_remove

        config = {
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            }
        }

        self.builder = compose1.ComposeV1Builder(
            'one', config, runner.return_value)

        self.builder.runner = runner
        self.assertTrue(self.builder.delete_updated('one', [['one']]))
        mock_inspect.assert_called_once_with('one')
        mock_remove.assert_called_once_with('one')

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_delete_updated_update_config(self, runner):
        mock_inspect = mock.MagicMock()
        mock_inspect.side_effect = [
            {
                "Id": ("d038dccebdb0996ed36ab4ff06e7c424b3816d67664aa11e00642"
                       "be5e00cec55"),
                "Config": {
                    "Labels": {
                        "config_data": """{
                            \"start_order\": 1,
                            \"image": \"centos:7\"
                        }"""
                    },
                    "Image": "127.0.0.1:8787/centos:7"
                },
                "Image": "sha256:1"
            },
            "sha256:1"
        ]

        runner.inspect = mock_inspect
        mock_remove = mock.MagicMock()
        runner.remove_container = mock_remove

        config = {
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            }
        }

        self.builder = compose1.ComposeV1Builder(
            'one', config, runner.return_value)

        self.builder.runner = runner
        self.assertTrue(self.builder.delete_updated('one', [['one']]))
        mock_inspect.assert_called_once_with('one')
        mock_remove.assert_called_once_with('one')

    @mock.patch('paunch.runner.DockerRunner', autospec=True)
    def test_delete_updated_update_image(self, runner):
        mock_inspect = mock.MagicMock()
        mock_inspect.side_effect = [
            {
                "Id": ("d038dccebdb0996ed36ab4ff06e7c424b3816d67664aa11e00642"
                       "be5e00cec55"),
                "Config": {
                    "Labels": {
                        "config_data": """{
                            \"start_order\": 0,
                            \"image": \"centos:7\"
                        }"""
                    },
                    "Image": "127.0.0.1:8787/centos:7"
                },
                "Image": "sha256:1"
            },
            "sha256:2"
        ]

        runner.inspect = mock_inspect
        mock_remove = mock.MagicMock()
        runner.remove_container = mock_remove

        config = {
            'one': {
                'start_order': 0,
                'image': 'centos:7',
            }
        }

        self.builder = compose1.ComposeV1Builder(
            'one', config, runner.return_value)

        self.builder.runner = runner
        self.assertTrue(self.builder.delete_updated('one', [['one']]))
        calls = [
            mock.call('one'),
            mock.call('127.0.0.1:8787/centos:7',
                      '{{index .Id}}',
                      type='image')
        ]
        mock_inspect.has_calls(calls)
        mock_remove.assert_called_once_with('one')
