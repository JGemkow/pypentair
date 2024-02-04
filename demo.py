"""Demo."""
from __future__ import annotations

import argparse
import asyncio
import logging
from operator import itemgetter
import os
from pathlib import Path

from deepdiff import DeepDiff
from dotenv import set_key

from pypentair import Pentair, PentairAuthenticationError

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
    _selectedDeviceId = None
    _filteredDevices = pentair.get_if3_devices()

    _deviceCount = len(_filteredDevices)
    if _deviceCount == 0:
        print("No compatible devices found on this account")
    else:
        print(str(_deviceCount) + " compatible device(s) found. Please select device to add to monitor\n")
        print(_filteredDevices)
        for i in range(_deviceCount):
            print(str(i+1) + ". " + _filteredDevices[i].nickName + " (" + _filteredDevices[i].model + ")")

        validSelection = False
        print("\n")
        while validSelection == False:
            selection = input("Please select a device by number in the list: ")
            try:
                selection = int(selection)
                if selection in range(1, _deviceCount+1):
                    validSelection = True
                    _selectedDeviceId = _filteredDevices[i-1].deviceId
                else: 
                    print("Invalid choice.\n")
                    validSelection = False
            except:
                print("Invalid choice.")
                validSelection = False

    if _selectedDeviceId != None:
        while True:
            device = {}
            monitorPasses = 0
            while monitorPasses < 5:
                try:
                    # Compare single device
                    _device = pentair.get_if3_pump(_selectedDeviceId)

                    diff = DeepDiff(
                        device,
                        _device,
                        ignore_order=True,
                        report_repetition=True
                    )
                    
                    logging.debug(diff if diff else "No changes")
                    device = _device
                    print(_device)
                except Exception as ex:  # pylint: disable=broad-except
                    logging.error(ex)
                if not keep_alive:
                    break
                await asyncio.sleep(30)
                monitorPasses += 1

            # Once monitor has completed five times, attempt a change
            validProgramIDOptions = list(program.id for program in device.enabledPrograms)
            print("Testing pump change..")
            print("Current program is " + device.activeProgramName)
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
            pentair.change_if3_pump_program(_selectedDeviceId, selectedProgramID)
    
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
