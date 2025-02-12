"""
Copyright 2022 The Magma Authors.
This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree.
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import ipaddress
import time
import unittest

import s1ap_types
from integ_tests.s1aptests import s1ap_wrapper
from integ_tests.s1aptests.s1ap_utils import SessionManagerUtil, SpgwUtil
from s1ap_utils import MagmadUtil


class TestIpv6NonNatDedBearerUlTcp(unittest.TestCase):
    """Integration Test: TestIpv6NonNatDedBearerUlTcp"""

    def __init__(self, method_name: str = ...) -> None:
        """Initialize unittest class"""
        super().__init__(methodName=method_name)
        self.magma_utils = MagmadUtil(None)
        self._sessionManager_util = SessionManagerUtil()
        self._spgw_util = SpgwUtil()

    def setUp(self):
        """Initialize before test case execution"""
        self.magma_utils.disable_nat(ip_version=6)
        self._s1ap_wrapper = s1ap_wrapper.TestWrapper(ip_version=6)

    def tearDown(self):
        """Cleanup after test case execution"""
        self._s1ap_wrapper.cleanup()
        self.magma_utils.enable_nat(ip_version=6)

    def test_ipv6_non_nat_ded_bearer_ul_tcp(self):
        """Basic attach/detach and UL TCP ipv6 data test with dedicated bearer"""
        num_ues = 1

        magma_apn = {
            "apn_name": "magma",  # APN-name
            "qci": 9,  # qci
            "priority": 15,  # priority
            "pre_cap": 1,  # preemption-capability
            "pre_vul": 0,  # preemption-vulnerability
            "mbr_ul": 200000000,  # MBR UL
            "mbr_dl": 100000000,  # MBR DL
            "pdn_type": 1,  # PDN Type 0-IPv4,1-IPv6,2-IPv4v6
        }

        wait_for_s1 = True
        ue_ips = ["fdee::"]
        apn_list = [magma_apn]

        self._s1ap_wrapper.configUEDevice(num_ues, [], ue_ips)

        req = self._s1ap_wrapper.ue_req
        ue_id = req.ue_id
        print(
            "************************* Running End to End attach for ",
            "UE id ",
            req.ue_id,
        )

        self._s1ap_wrapper.configAPN(
            "IMSI" + "".join([str(j) for j in req.imsi]),
            apn_list,
            default=False,
        )

        # Now actually complete the attach
        # PDN type values sent in NAS message are different from
        # the values used in s6a (APN config)
        # PDN Type 1-IPv4,2-IPv6,3-IPv4v6
        self._s1ap_wrapper.s1_util.attach(
            ue_id,
            s1ap_types.tfwCmd.UE_END_TO_END_ATTACH_REQUEST,
            s1ap_types.tfwCmd.UE_ATTACH_ACCEPT_IND,
            s1ap_types.ueAttachAccept_t,
            pdn_type=2,
        )

        # Wait on EMM Information from MME
        self._s1ap_wrapper._s1_util.receive_emm_info()

        # Receive Router Advertisement message
        apn = "magma"
        response = self._s1ap_wrapper.s1_util.get_response()
        self.assertEqual(
            response.msg_type, s1ap_types.tfwCmd.UE_ROUTER_ADV_IND.value,
        )
        router_adv = response.cast(s1ap_types.ueRouterAdv_t)
        print(
            "********** Received Router Advertisement for APN-%s"
            " bearer id-%d" % (apn, router_adv.bearerId),
        )
        ipv6_addr = "".join([chr(i) for i in router_adv.ipv6Addr]).rstrip(
            "\x00",
        )
        print("********** UE IPv6 address: ", ipv6_addr)
        default_ipv6 = ipaddress.ip_address(ipv6_addr)
        self._s1ap_wrapper.s1_util.update_ipv6_address(ue_id, ipv6_addr)

        print(
            "********************** Sending RAR for IMSI",
            "".join([str(i) for i in req.imsi]),
        )

        # QoS
        qos = {
            "qci": 1,  # qci value [1 to 9]
            "priority": 1,  # Range [0-255]
            "max_req_bw_ul": 10000000,  # MAX bw Uplink
            "max_req_bw_dl": 15000000,  # MAX bw Downlink
            "gbr_ul": 1000000,  # GBR Uplink
            "gbr_dl": 2000000,  # GBR Downlink
            "arp_prio": 1,  # ARP priority
            "pre_cap": 1,  # pre-emption capability
            "pre_vul": 1,  # pre-emption vulnerability
        }

        flow_list = self._spgw_util.create_default_ipv6_flows()
        policy_id = "magma"

        self._sessionManager_util.send_ReAuthRequest(
            "IMSI" + "".join([str(i) for i in req.imsi]),
            policy_id,
            flow_list,
            qos,
        )
        response = self._s1ap_wrapper.s1_util.get_response()
        self.assertEqual(
            response.msg_type, s1ap_types.tfwCmd.UE_ACT_DED_BER_REQ.value,
        )
        act_ded_ber_req_ims_apn = response.cast(
            s1ap_types.UeActDedBearCtxtReq_t,
        )
        self._s1ap_wrapper.sendActDedicatedBearerAccept(
            req.ue_id, act_ded_ber_req_ims_apn.bearerId,
        )
        print(
            "************* Added dedicated bearer",
            act_ded_ber_req_ims_apn.bearerId,
        )

        # Sleep before verifying flows
        print("********** Sleeping for 5 seconds")
        time.sleep(5)
        # Verify flow rules
        num_ul_flows = 2
        dl_flow_rules = {
            default_ipv6: [flow_list],
        }
        # Verify if flow rules are created
        self._s1ap_wrapper.s1_util.verify_flow_rules(
            num_ul_flows, dl_flow_rules, ipv6_non_nat=True,
        )

        print(
            "************************* Running UE uplink (TCP) for UE id ",
            req.ue_id,
        )
        with self._s1ap_wrapper.configUplinkTest(req, duration=1) as test:
            test.verify()
        print(
            "************************* Running UE detach for UE id ",
            req.ue_id,
        )
        # Now detach the UE
        self._s1ap_wrapper.s1_util.detach(
            req.ue_id,
            s1ap_types.ueDetachType_t.UE_NORMAL_DETACH.value,
            wait_for_s1,
        )

        print("********** Sleeping for 5 seconds")
        time.sleep(5)
        # Verify that all UL/DL flows are deleted
        self._s1ap_wrapper.s1_util.verify_flow_rules_deletion()


if __name__ == "__main__":
    unittest.main()
