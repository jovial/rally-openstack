# All Rights Reserved.
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
import re
import shutil
import subprocess


from rally.common.io import subunit_v2
from rally.common import logging
from rally.common import utils as common_utils
from rally import exceptions
from rally.verification import context
from rally.verification import manager
from rally.verification import utils


LOG = logging.getLogger(__name__)

TEST_NAME_RE = re.compile(r"^[a-zA-Z_.0-9]+(\[[a-zA-Z-_,=0-9]*\])?$")


def _expand_skip_list(load_list, regexps):
    """Returns mapping of test names to the reason why the test was skipped.

    The dictionary includes all tests in``load_list`` that match a key in
    ``regexps``.
    """
    result = {}
    if not regexps:
        return result
    for regex, reason in regexps.items():
        try:
            pattern = re.compile(regex)
            for test in load_list:
                if pattern.search(test):
                    result[test] = reason
        except re.error:
            # assume regex is a test id, eg: tempest.api.compute.admin.
            # test_flavors.FlavorsAdminTestJSON.
            # test_create_flavor_using_string_ram
            # [id-3b541a2e-2ac2-4b42-8b8d-ba6e22fcd4da]
            result[regex] = reason
            continue
    return result


@context.configure("testr", order=999)
class TestrContext(context.VerifierContext):
    """Context to transform 'run_args' into CLI arguments for testr."""

    def __init__(self, ctx):
        super(TestrContext, self).__init__(ctx)
        self._tmp_files = []

    def setup(self):
        use_testr = getattr(self.verifier.manager, "_use_testr", True)

        if use_testr:
            base_cmd = "testr"
        else:
            base_cmd = "stestr"
        self.context["testr_cmd"] = [base_cmd, "run", "--subunit"]
        run_args = self.verifier.manager.prepare_run_args(
            self.context.get("run_args", {}))

        concurrency = run_args.get("concurrency", 0)
        if concurrency == 0 or concurrency > 1:
            if use_testr:
                self.context["testr_cmd"].append("--parallel")
        if concurrency >= 1:
            if concurrency == 1 and not use_testr:
                self.context["testr_cmd"].append("--serial")
            else:
                self.context["testr_cmd"].extend(
                    ["--concurrency", str(concurrency)])

        load_list = run_args.get("load_list")
        skip_list = run_args.get("skip_list")

        if skip_list:
            if not load_list:
                load_list = self.verifier.manager.list_tests()
            skip_list = _expand_skip_list(load_list, skip_list)
            # update run_args so that we can access the skip reason when
            # building the metadata
            run_args["skip_list"] = skip_list
            load_list = set(load_list) - set(skip_list)
        if load_list:
            load_list_file = common_utils.generate_random_path()
            with open(load_list_file, "w") as f:
                f.write("\n".join(load_list))
            self._tmp_files.append(load_list_file)
            self.context["testr_cmd"].extend(["--load-list", load_list_file])

        if run_args.get("failed"):
            self.context["testr_cmd"].append("--failing")

        if run_args.get("pattern"):
            self.context["testr_cmd"].append(run_args.get("pattern"))

    def cleanup(self):
        for f in self._tmp_files:
            if os.path.exists(f):
                os.remove(f)


class TestrLauncher(manager.VerifierManager):
    """Testr/sTestr wrapper."""

    def __init__(self, *args, **kwargs):
        super(TestrLauncher, self).__init__(*args, **kwargs)
        self._use_testr = os.path.exists(os.path.join(
            self.repo_dir, ".testr.conf"))

    @property
    def run_environ(self):
        return self.environ

    def _init_testr(self):
        """Initialize testr."""
        test_repository_dir = os.path.join(self.base_dir, ".testrepository")
        # NOTE(andreykurilin): Is there any possibility that .testrepository
        #   presents in clear repo?!
        if not os.path.isdir(test_repository_dir):
            LOG.debug("Initializing testr.")
            if self._use_testr:
                base_cmd = "testr"
            else:
                base_cmd = "stestr"
            try:
                utils.check_output([base_cmd, "init"], cwd=self.repo_dir,
                                   env=self.environ)
            except (subprocess.CalledProcessError, OSError):
                if os.path.exists(test_repository_dir):
                    shutil.rmtree(test_repository_dir)
                raise exceptions.RallyException("Failed to initialize testr.")

    def install(self):
        super(TestrLauncher, self).install()
        self._init_testr()

    def list_tests(self, pattern=""):
        """List all tests."""
        if self._use_testr:
            cmd = ["testr", "list-tests", pattern]
        else:
            cmd = ["stestr", "list", pattern]
        output = utils.check_output(cmd,
                                    cwd=self.repo_dir, env=self.environ,
                                    debug_output=False)
        return [t for t in output.split("\n") if TEST_NAME_RE.match(t)]

    def run(self, context):
        """Run tests."""
        testr_cmd = context["testr_cmd"]
        run_args = context.get("run_args", {})
        LOG.debug("Test(s) started by the command: '%s'."
                  % " ".join(testr_cmd))
        stream = subprocess.Popen(testr_cmd, env=self.run_environ,
                                  cwd=self.repo_dir,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)
        xfail_list = run_args.get("xfail_list")
        skip_list = run_args.get("skip_list")
        results = subunit_v2.parse(stream.stdout, live=True,
                                   expected_failures=xfail_list,
                                   skipped_tests=skip_list,
                                   logger_name=self.verifier.name)
        stream.wait()

        return results

    def prepare_run_args(self, run_args):
        """Prepare 'run_args' for testr context.

        This method is called by TestrContext before transforming 'run_args'
        into CLI arguments for testr.
        """
        return run_args
