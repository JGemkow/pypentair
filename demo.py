"""Demo."""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
from operator import itemgetter
import os
from pathlib import Path

from deepdiff import DeepDiff
from dotenv import set_key

from pypentair import Pentair, PentairAuthenticationError
from pypentair.pentair import PentairIF3Pump

logging.basicConfig(level=logging.DEBUG)

ENV_PATH = Path(".env")

USERNAME = os.getenv("PENTAIR_USERNAME")
PASSWORD = os.getenv("PENTAIR_PASSWORD")

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ID_TOKEN = os.getenv("ID_TOKEN")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")


async def main(keep_alive: bool = False) -> None:
    """Main."""
    use_token = all((ACCESS_TOKEN, ID_TOKEN, REFRESH_TOKEN))
    try:
        pentair = token_login() if use_token else password_login()
    except Exception as ex:  # pylint: disable=broad-except
        print(ex)
        return

    for key, value in pentair.get_tokens().items():
        set_key(ENV_PATH, key.upper(), value)

    # Get devices
    selectedDeviceId = None
    devices = pentair.get_devices()
    filteredDevices = [device for device in devices if device.deviceType == "IF31"]

    deviceCount = len(filteredDevices)
    if deviceCount == 0:
        print("No compatible devices found on this account")
    else:
        print(str(deviceCount) + " compatible device(s) found. Please select device to add to monitor\n")
        print(filteredDevices)
        for i in range(deviceCount):
            print(str(i+1) + ". " + filteredDevices[i].nickName + " (" + filteredDevices[i].model + ")")

        validSelection = False
        print("\n")
        while validSelection == False:
            selection = input("Please select a device by number in the list: ")
            try:
                selection = int(selection)
                if selection in range(1, deviceCount+1):
                    validSelection = True
                    selectedDeviceId = filteredDevices[i-1].deviceId
                else: 
                    print("Invalid choice.\n")
                    validSelection = False
            except:
                print("Invalid choice.")
                validSelection = False

    if selectedDeviceId != None:
        while True:
            monitorPasses = 0
            while monitorPasses < 2:
                try:
                    # Compare single device
                    deviceFromAPI: PentairIF3Pump = pentair.get_device(selectedDeviceId)

                    if monitorPasses != 0:
                        diff = DeepDiff(
                            device,
                            deviceFromAPI,
                            ignore_order=True,
                            report_repetition=True
                        )
                        
                        logging.debug(diff if diff else "No changes")
                    
                    current_time = datetime.datetime.now()
                    print("UTC Time:", current_time)  
                    if deviceFromAPI.activeProgramName is None:
                        print("No running program at the moment.")
                    else:
                        print("Current program is " + deviceFromAPI.activeProgramName)
                    print("Current power consumption is " + str(deviceFromAPI.currentPowerConsumption))
                    print("Current estimated flow is " + str(deviceFromAPI.currentEstimatedFlow))
                    device = deviceFromAPI
                except Exception as ex:  # pylint: disable=broad-except
                    logging.error(ex)
                if not keep_alive:
                    break
                await asyncio.sleep(30)
                monitorPasses += 1

            # Once monitor has completed five times, attempt a change
            validProgramIDOptions = list(program.id for program in device.enabledPrograms)
            print("Testing pump change..")
            print("Choose a new pump program to switch to:")
            if device.activeProgramNumber != None:
                validProgramIDOptions.append(0)
                print("0. Stop")
            for program in device.enabledPrograms:
                print(str(program.id) + ". " + program.name)

            print("\n")
            validSelection = False
            while validSelection == False:
                try:
                    selectedProgramID = int(input("Select one by ID: "))
                    
                    if selectedProgramID in validProgramIDOptions:
                        validSelection = True
                    else:
                        print("Invalid selection.")
                except:
                    print("Invalid selection.")

            if (selectedProgramID == 0):
                print("Stopping current program.")
            else:
                print("Switching to program " + str(selectedProgramID))
            pentair.change_active_pump_program(device, selectedProgramID)
    
            for key, value in pentair.get_tokens().items():
                set_key(ENV_PATH, key.upper(), value)

def password_login() -> Pentair:
    """Login using username/password."""
    if not (username := USERNAME):
        username = input("Enter username: ")
    if not (password := PASSWORD):
        password = input("Enter password: ")
    pentair = Pentair(username=username)
    pentair.authenticate(password=password)
    return pentair


def token_login() -> Pentair:
    """Login using tokens."""
    pentair = Pentair(
        access_token=ACCESS_TOKEN, id_token=ID_TOKEN, refresh_token=REFRESH_TOKEN
    )
    try:
        pentair.get_user()
    except PentairAuthenticationError:
        return password_login()
    return pentair

parser = argparse.ArgumentParser(description="Login to Pentair Home and list devices.")
parser.add_argument(
    "-ka",
    "--keep-alive",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="If true, run indefinitely while polling every 30 seconds.",
)
args = parser.parse_args()

if __name__ == "__main__":
    asyncio.run(main(args.keep_alive))
