"""Classes for interacting with the Glowmarkt API."""

from __future__ import annotations

from pprint import pprint
import time
import sys
from typing import Any, Callable, Dict, List

import paho.mqtt.client as mqtt
import requests
from homeassistant import exceptions
from paho.mqtt.client import ConnectFlags, MQTTMessage
from paho.mqtt.enums import MQTTErrorCode, CallbackAPIVersion
from paho.mqtt.reasoncodes import ReasonCode

from .mqttpayload import MQTTPayload

from .glowdata import SmartMeter  # isort:skip

import logging

LOGGER = logging.getLogger(__package__)

class Glow:
    """Bindings for the Hildebrand Glow Platform API."""

    BASE_URL = "https://api.glowmarkt.com/api/v0-1"
    HILDEBRAND_MQTT_HOST = "glowmqtt.energyhive.com"
    HILDEBRAND_MQTT_TOPIC = "SMART/+/{hardwareId}"

    username: str
    password: str

    token: str

    hardwareId: str
    broker: mqtt.Client

    data: SmartMeter = SmartMeter(None, None, None)

    callbacks: List[Callable] = []

    def __init__(self, app_id: str, username: str, password: str, token: str = "", token_exp: int = sys.maxsize) -> None:
        """Create an authenticated Glow object."""
        self.app_id = app_id
        self.username = username
        self.password = password

        self.token = token
        self.token_exp = token_exp

        self.broker = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
        self.broker.username_pw_set(username=self.username, password=self.password)
        self.broker.on_connect = self._cb_on_connect
        self.broker.on_message = self._cb_on_message

        self.broker_active = False

    def authenticate(self) -> Dict[str, Any]:
        """Attempt to authenticate with Glowmarkt."""
        if self.token and self.token_exp > int(time.time()):
            LOGGER.debug("using existing glow token")
            return {"token": self.token, "exp": self.token_exp}
        
        if self.token and self.token_exp <= int(time.time()):
            LOGGER.debug("glow token expired")
            raise ExpiredToken
        
        url = f"{self.BASE_URL}/auth"
        auth = {"username": self.username, "password": self.password, "applicationId": self.app_id}
        headers = {
            "User-Agent": "curl/7.64.1",
            "applicationId": self.app_id,
            "Accept": "application/json, */*",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, json=auth, headers=headers, timeout=30)
        except requests.Timeout as e:
            LOGGER.error("failed to authenticate - %s", e)
            raise CannotConnect

        LOGGER.debug("connected to glow")
        data = response.json()

        if data["valid"]:
            LOGGER.debug("got glow token")
            self.token = data["token"]
            self.token_exp = data["exp"]
            return data
        else:
            LOGGER.error("failed to authenticate - %s", data)
            raise InvalidAuth

    def retrieve_devices(self) -> List[Dict[str, Any]]:
        """Retrieve the Zigbee devices known to Glowmarkt for the authenticated user."""
        url = f"{self.BASE_URL}/device"
        headers = {"applicationId": self.app_id, "token": self.token, "Accept": "application/json"}

        try:
            response = requests.get(url, headers=headers)
        except requests.Timeout:
            raise CannotConnect

        if response.status_code != 200:
            raise InvalidAuth

        data = response.json()
        return data

    def retrieve_cad_hardwareId(self) -> str:
        """Locate the Consumer Access Device's hardware ID from the devices list."""
        ZIGBEE_GLOW_STICK = "1027b6e8-9bfd-4dcb-8068-c73f6413cfaf"
        ZIGBEE_GLOW_DISPLAY_SMETS2 = "b91cf82f-aafe-47f4-930a-b2ed1c7b2691"

        devices = self.retrieve_devices()

        cad: Dict[str, Any] = next(
            (
                dev
                for dev in devices
                if dev["deviceTypeId"]
                in [ZIGBEE_GLOW_STICK, ZIGBEE_GLOW_DISPLAY_SMETS2]
            ),
            {},
        )

        if "hardwareId" in cad:
            self.hardwareId = cad["hardwareId"]

            return self.hardwareId
        else:
            raise NoCADAvailable

    def connect_mqtt(self) -> None:
        """Connect the internal MQTT client to the discovered CAD."""
        self.broker.connect(self.HILDEBRAND_MQTT_HOST)
        self.broker.loop_start()

    async def disconnect(self) -> None:
        """Disconnect the internal MQTT client."""
        self.broker.loop_stop()

    def _cb_on_connect(
        self,
        client: Any,
        userdata: Any,
        flags: ConnectFlags,
        rc: ReasonCode,
        properties: Any,
    ) -> None:
        """Receive a CONNACK message from the server."""
        client.subscribe(
            [(self.HILDEBRAND_MQTT_TOPIC.format(hardwareId=self.hardwareId), 0)]
        )

        self.broker_active = True

    def _cb_on_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        """Receive notice the MQTT connection has disconnected."""
        self.broker_active = False

    def _cb_on_message(self, client: Any, userdata: Any, msg: MQTTMessage) -> None:
        """Receive a PUBLISH message from the server."""
        LOGGER.debug("got mqtt msg - %s", msg.payload)
        payload = MQTTPayload(msg.payload)
        self.data = SmartMeter.from_mqtt_payload(payload)

        for callback in self.callbacks:
            callback(payload)

    def retrieve_resources(self) -> List[Dict[str, Any]]:
        """Retrieve the resources known to Glowmarkt for the authenticated user."""
        url = f"{self.BASE_URL}/resource"
        headers = {"applicationId": self.app_id, "token": self.token, "Accept": "application/json"}

        try:
            response = requests.get(url, headers=headers)
        except requests.Timeout:
            raise CannotConnect

        if response.status_code != 200:
            raise InvalidAuth

        data = response.json()
        return data

    def current_usage(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve the current usage for a specified resource."""
        url = f"{self.BASE_URL}/resource/{resource}/current"
        headers = {"applicationId": self.app_id, "token": self.token, "Accept": "application/json"}

        try:
            response = requests.get(url, headers=headers)
        except requests.Timeout:
            raise CannotConnect

        if response.status_code != 200:
            raise InvalidAuth

        data = response.json()
        return data

    def register_on_message_callback(self, callback: Callable) -> None:
        """Register a live sensor for dispatching MQTT messages."""
        self.callbacks.append(callback)


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""

class ExpiredToken(exceptions.HomeAssistantError):
    """Error to indicate there is an expired token."""

class NoCADAvailable(exceptions.HomeAssistantError):
    """Error to indicate no CADs were found."""
