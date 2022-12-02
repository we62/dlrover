# Copyright 2022 The EasyDL Authors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

from dlrover.python.common.constants import DistributionStrategy, NodeType
from dlrover.python.common.node import Node, NodeGroupResource, NodeResource
from dlrover.python.master.scaler.base_scaler import ScalePlan
from dlrover.python.master.scaler.pod_scaler import PodScaler
from dlrover.python.tests.test_utils import mock_k8s_client


class PodScalerTest(unittest.TestCase):
    def setUp(self) -> None:
        mock_k8s_client()

    def test_init_pod_template(self):
        scaler = PodScaler("elasticjob-sample", "default")
        self.assertEqual(scaler._distribution_strategy, "parameter_server")
        worker_template = scaler._replica_template[NodeType.WORKER]
        self.assertEqual(
            worker_template.image, "dlrover/elasticjob:iris_estimator"
        )
        self.assertEqual(worker_template.restart_policy, "Never")
        self.assertListEqual(
            worker_template.command,
            [
                "python",
                "-m",
                "model_zoo.iris.dnn_estimator",
                "--batch_size=32",
                "--training_steps=1000",
            ],
        )

    def test_create_pod(self):
        scaler = PodScaler("elasticjob-sample", "default")
        scaler._distribution_strategy = DistributionStrategy.PARAMETER_SERVER
        resource = NodeResource(4, 8192)
        node = Node(NodeType.WORKER, 0, resource, task_index=0)
        job_resource = {
            NodeType.WORKER: NodeGroupResource(3, NodeResource(4, 2048)),
            NodeType.CHIEF: NodeGroupResource(1, NodeResource(4, 2048)),
            NodeType.PS: NodeGroupResource(2, NodeResource(4, 2048)),
        }
        ps_addrs = [
            "elasticjob-sample-edljob-ps-0",
            "elasticjob-sample-edljob-ps-1",
        ]
        pod = scaler._create_pod(node, job_resource, ps_addrs)
        self.assertEqual(
            pod.metadata.name, "elasticjob-sample-edljob-worker-0"
        )
        main_container = pod.spec.containers[0]
        self.assertEqual(main_container.resources.limits["cpu"], 4)
        self.assertEqual(main_container.resources.limits["memory"], "8192Mi")
        self.assertEqual(main_container.env[-1].name, "TF_CONFIG")
        self.assertTrue(
            """{"type": "worker", "index": 0}"""
            in main_container.env[-1].value
        )
        node = Node(NodeType.CHIEF, 0, resource, task_index=0)
        pod = scaler._create_pod(node, job_resource, ps_addrs)
        main_container = pod.spec.containers[0]
        self.assertTrue(
            """{"type": "chief", "index": 0}""" in main_container.env[-1].value
        )

        node = Node(NodeType.PS, 0, resource, task_index=0)
        pod = scaler._create_pod(node, job_resource, ps_addrs)
        main_container = pod.spec.containers[0]
        self.assertTrue(
            """{"type": "ps", "index": 0}""" in main_container.env[-1].value
        )

    def test_create_service(self):
        scaler = PodScaler("elasticjob-sample", "default")
        service = scaler._create_service(
            NodeType.WORKER, 0, "elasticjob-sample-edljob-worker-0"
        )
        self.assertEqual(service.spec.selector["elastic-replica-index"], "0")
        self.assertEqual(
            service.spec.selector["elastic-replica-type"], "worker"
        )

    def test_scale(self):
        scaler = PodScaler("elasticjob-sample", "default")
        scaler._distribution_strategy = DistributionStrategy.PARAMETER_SERVER
        resource = NodeResource(4, 8192)
        scale_plan = ScalePlan()
        scale_plan.node_group_resources = {
            NodeType.WORKER: NodeGroupResource(5, resource),
            NodeType.CHIEF: NodeGroupResource(1, resource),
            NodeType.PS: NodeGroupResource(2, resource),
        }
        scaler.scale(scale_plan)
        self.assertEqual(len(scaler._initial_nodes), 3)

        scale_plan.node_group_resources = {
            NodeType.WORKER: NodeGroupResource(3, resource),
            NodeType.CHIEF: NodeGroupResource(1, resource),
            NodeType.PS: NodeGroupResource(2, resource),
        }
        scaler.scale(scale_plan)
        self.assertEqual(len(scaler._initial_nodes), 1)