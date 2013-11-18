# Copyright 2013: Mirantis Inc.
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

import urlparse

from rally import consts
from rally import db
from rally.deploy import engine
from rally import objects
from rally import orchestrator


class MultihostEngine(engine.EngineFactory):
    """Deploy multihost cloud with existing engines.

    Sample configuration:

    {
        "name": "MultihostEngine",
        "controller": {
            "name": "DevstackEngine",
            "provier": {
                "name": "DummyProvider"
            }
        },
        "nodes": [
            {"name": "Engine1", "config": "Config1"},
            {"name": "Engine2", "config": "Config2"},
            {"name": "Engine3", "config": "Config3"},
        ]
    }

    If {controller_ip} is specified in configuration values, it will be
    replaced with controller address taken from endpoint returned by
    controller engine:

    ...
    "nodes": [
        {
            "name": "DevstackEngine",
            "localrc": {
                "GLANCE_HOSTPORT": "{controller_ip}:9292",
    ...

    """

    def __init__(self, *args, **kwargs):
        super(MultihostEngine, self).__init__(*args, **kwargs)
        self.config = self.deployment['config']
        self.nodes = []

    def _deploy_node(self, config):
        deployment = objects.Deployment(config=config,
                                        parent_uuid=self.deployment['uuid'])
        deployer = engine.EngineFactory.get_engine(config['name'], deployment)
        with deployer:
            endpoints = deployer.make_deploy()
        return deployer, endpoints

    def _update_controller_ip(self, obj):
        if isinstance(obj, dict):
            keyval = obj.iteritems()
        elif isinstance(obj, list):
            keyval = enumerate(obj)

        for key, value in keyval:
            if isinstance(value, basestring):
                obj[key] = value.format(controller_ip=self.controller_ip)
            elif type(value) in (dict, list):
                self._update_controller_ip(value)

    def deploy(self):
        self.deployment.update_status(consts._DeployStatus.DEPLOY_SUBDEPLOY)
        self.controller, self.endpoints = self._deploy_node(
            self.config['controller'])
        endpoint = self.endpoints[0]
        self.controller_ip = urlparse.urlparse(endpoint.auth_url).hostname

        for node_config in self.config['nodes']:
            self._update_controller_ip(node_config)
            self.nodes.append(self._deploy_node(node_config)[0])
        return self.endpoints

    def cleanup(self):
        subdeploys = db.deployment_list(parent_uuid=self.deployment['uuid'])
        for subdeploy in subdeploys:
            orchestrator.api.destroy_deploy(subdeploy['uuid'])
