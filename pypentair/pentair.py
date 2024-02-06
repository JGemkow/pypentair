"""Pentair account."""
from __future__ import annotations
from typing import List

import logging
from typing import Any, Final
from urllib.parse import urljoin

import requests
from boto3 import client as boto_client
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.exceptions import ClientError
from pycognito import Cognito

from .const import CLIENT_ID, IDENTITY_POOL_ID, REGION_NAME, USER_POOL_ID
from .exceptions import PentairAuthenticationError
from .utils import decode, redact
import json as jsonLib

_LOGGER = logging.getLogger(__name__)

BASE_URL: Final = "https://api.pentair.cloud/"

class PentairDevice:
    def __init__(self, deviceId: int, nickName: str, deviceType: str, maker: str, model: str, softwareVersion: str):
        self.deviceId: str = deviceId
        self.nickName: str = nickName
        self.maker: str = maker
        self.model: str = model
        self.deviceType: str = deviceType
        self.softwareVersion: str = softwareVersion

class PentairIF3PumpProgram:
    def __init__(self, id: int, name: str):
        self.id: int = id
        self.name: str = name

class PentairIF3Pump(PentairDevice):
    def __init__(self, deviceId: str, nickName: str, deviceType: str, maker:str, model: str, softwareVersion:str, activeProgramNumber: int | None, activeProgramName: str | None, 
                 enabledPrograms: list, currentPowerConsumption: int, currentMotorSpeed: float, currentEstimatedFlow: float):
        PentairDevice.__init__(self, deviceId, nickName, deviceType, maker, model, softwareVersion)

        self.activeProgramNumber: int | None = activeProgramNumber
        self.activeProgramName: str | None = activeProgramName
        self.currentPowerConsumption: int = currentPowerConsumption
        self.currentMotorSpeed: float = currentMotorSpeed
        self.currentEstimatedFlow: float = currentEstimatedFlow
        self.enabledPrograms: List[PentairIF3PumpProgram] = enabledPrograms

class Pentair:
    """Pentair account."""

    _user: Cognito | None = None
    _auth: SigV4Auth | None = None

    def __init__(
        self,
        *,
        username: str | None = None,
        access_token: str | None = None,
        id_token: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        """Initialize."""
        self._username = username
        self._access_token = access_token
        self._id_token = id_token
        self._refresh_token = refresh_token

    @property
    def access_token(self) -> str | None:
        """Return the access token."""
        return self._user.access_token if self._user else self._access_token

    @property
    def id_token(self) -> str | None:
        """Return the id token."""
        return self._user.id_token if self._user else self._id_token

    @property
    def refresh_token(self) -> str | None:
        """Return the refresh token."""
        return self._user.refresh_token if self._user else self._refresh_token

    def get_user(self) -> Cognito:
        """Return the Cognito user."""
        if self._user is None:
            self._user = Cognito(
                decode(USER_POOL_ID),
                decode(CLIENT_ID),
                username=self._username,
                access_token=self.access_token,
                id_token=self.id_token,
                refresh_token=self.refresh_token,
            )
            if self.access_token or self.id_token:
                try:
                    self._user.check_token()
                    self._user.verify_tokens()
                except ClientError as err:
                    _LOGGER.error(err)
                    raise PentairAuthenticationError(err) from err
        return self._user

    def get_auth(self) -> SigV4Auth:
        """Return the SigV4Auth."""
        if self.get_user().check_token() or self._auth is None:
            client = boto_client("cognito-identity", region_name=REGION_NAME)
            logins = {
                f"cognito-idp.{REGION_NAME}.amazonaws.com/{decode(USER_POOL_ID)}": self.id_token
            }
            response = client.get_id(
                IdentityPoolId=decode(IDENTITY_POOL_ID), Logins=logins
            )
            response = client.get_credentials_for_identity(
                IdentityId=response["IdentityId"], Logins=logins
            )
            credentials = Credentials(
                response["Credentials"]["AccessKeyId"],
                response["Credentials"]["SecretKey"],
                response["Credentials"]["SessionToken"],
            )
            self._auth = SigV4Auth(credentials, "execute-api", REGION_NAME)
        return self._auth

    def get_tokens(self) -> dict[str, str]:
        """Return the tokens."""
        if (user := self.get_user()).access_token:
            return {
                "access_token": user.access_token,
                "id_token": user.id_token,
                "refresh_token": user.refresh_token,
            }
        return {}

    def authenticate(self, password: str) -> None:
        """Authenticate a user."""
        try:
            self.get_user().authenticate(password=password)
        except ClientError as err:
            _LOGGER.error(err)
            raise PentairAuthenticationError(err) from err

    def logout(self) -> None:
        """Logout of all clients (including app)."""
        self.get_user().logout()

    def get_devices(self) -> List[PentairDevice]:
        """Get devices."""
        rawDevicesFromAPI = self.__get("device/device-service/user/devices")
        devices = []
        for item in rawDevicesFromAPI['data']:
            devices.append(
                PentairDevice(
                    deviceId=item['deviceId'],
                    nickName=item['productInfo']['nickName'],
                    deviceType=item['deviceType'],
                    maker=item['productInfo']['maker'],
                    model=item['productInfo']['model'],
                    softwareVersion=item['currentFWVersion']
                )
            )
        return devices
    
    def get_device(self, deviceId: str) -> PentairDevice:
        """Get device."""
        rawDeviceFromAPI = self.__get("device/device-service/user/device/" + deviceId)
    
        match rawDeviceFromAPI['data']['deviceType']:
            case "IF31":
                activeProgramNumber = int(rawDeviceFromAPI['data']['fields']['s14']['value'])
        
                device = PentairIF3Pump(
                    deviceId=rawDeviceFromAPI['data']['deviceId'],
                    nickName=rawDeviceFromAPI['data']['productInfo']['nickName'],
                    deviceType=rawDeviceFromAPI['data']['deviceType'],
                    maker=rawDeviceFromAPI['data']['productInfo']['maker'],
                    model=rawDeviceFromAPI['data']['productInfo']['model'],
                    softwareVersion=rawDeviceFromAPI['data']['fwVersion'],
                    activeProgramNumber= None if activeProgramNumber == 99 else activeProgramNumber + 1,
                    activeProgramName= None if activeProgramNumber == 99 else rawDeviceFromAPI['data']['fields']['zp' + str((activeProgramNumber+1)) + 'e2']['value'],
                    currentPowerConsumption=int(rawDeviceFromAPI['data']['fields']['s18']['value']),
                    currentMotorSpeed=0 if rawDeviceFromAPI['data']['fields']['s19']['value'] == "0" else (int(rawDeviceFromAPI['data']['fields']['s19']['value'])/10),
                    currentEstimatedFlow=0 if rawDeviceFromAPI['data']['fields']['s26']['value'] == "0" else (int(rawDeviceFromAPI['data']['fields']['s26']['value'])/10),
                    enabledPrograms=[]
                )

                # Loop through the 9 possible programs from the API body
                for i in range(1, 9):
                    if rawDeviceFromAPI['data']['fields']['zp' + str((i)) + 'e13']['value'] == "1":
                        device.enabledPrograms.append(
                            PentairIF3PumpProgram(
                                id=i,
                                name=rawDeviceFromAPI['data']['fields']['zp' + str((i)) + 'e2']['value']
                            )
                        )

                return device
            case _:
                device = PentairDevice(
                    deviceId=rawDeviceFromAPI['data']['deviceId'],
                    nickName=rawDeviceFromAPI['data']['productInfo']['nickName'],
                    deviceType=rawDeviceFromAPI['data']['deviceType'],
                    model=rawDeviceFromAPI['data']['productInfo']['model'],
                    softwareVersion=rawDeviceFromAPI['data']['currentFWVersion'],
                )
                return device

    def change_active_pump_program(self, pump: PentairIF3Pump, pumpProgramNumber: int) -> None:
            if (pumpProgramNumber == None or pumpProgramNumber == 0):
                configVariable = "zp" + str(pump.activeProgramNumber) + "e10"
            else: 
                configVariable = "zp" + str(pumpProgramNumber) + "e10"

            self.__update_device(pump.deviceId, {
                "payload": {
                    configVariable: "2" if pumpProgramNumber == 0 else "3"
                }
            })
    
    def __update_device(self, deviceId: str, data: Any) -> Any:
        """Update device."""
        return self.__put("device/device-service/user/device/" + deviceId, data)

    def __request(self, method: str, url: str, data: Any = None, **kwargs: Any) -> Any:
        """Make a request."""
        if (data == None):
            _LOGGER.debug("Making %s request to %s with %s", method, url, redact(kwargs))
            request = AWSRequest(
                method=method,
                url=urljoin(BASE_URL, url),
                headers={"x-amz-id-token": self.id_token},
            )
            self.get_auth().add_auth(request)
            prepped = request.prepare()
            response = requests.request(
                method, prepped.url, headers=prepped.headers, timeout=10, **kwargs
            )
            json = response.json()
        else:
            jsonData=jsonLib.dumps(data)
            _LOGGER.debug("Making %s request to %s with payload of %s and with %s", method, url, data, redact(kwargs))
            request = AWSRequest(
                method=method,
                url=urljoin(BASE_URL, url),
                headers={"x-amz-id-token": self.id_token},
                data=jsonData
            )
            self.get_auth().add_auth(request)
            prepped = request.prepare()
            response = requests.request(
                method, prepped.url, headers=prepped.headers, timeout=30, data=jsonData, **kwargs
            )
            json = response.json()
        _LOGGER.debug(
            "Received %s response from %s: %s", response.status_code, url, redact(json)
        )
        if (status_code := response.status_code) != 200:
            _LOGGER.error("Status: %s - %s", status_code, json)
            response.raise_for_status()
        return json

    def __get(self, url: str, **kwargs: Any) -> Any:
        """Make a get request."""
        return self.__request("get", url, **kwargs)

    def __post(  # pylint: disable=unused-private-member
        self, url: str, **kwargs: Any
    ) -> Any:
        """Make a post request."""
        return self.__request("post", url, **kwargs)

    def __put(  
        self, url: str, data, **kwargs: Any
    ) -> Any:
        """Make a put request."""
        return self.__request("put", url, data, **kwargs)
