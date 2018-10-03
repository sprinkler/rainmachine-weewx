# Copyright 2018 GreenElectronics LLC

from setup import ExtensionInstaller

def loader():
    return RainMachineInstaller()

class RainMachineInstaller(ExtensionInstaller):
    def __init__(self):
        super(RainMachineInstaller, self).__init__(
            version="0.2",
            name='rainmachine',
            description='Upload weather data to RainMachine smart irrigation controller.',
            author="Nicu Pavel",
            author_email="nicu.pavel@rainmachine.com",
            restful_services='user.rainmachine.RainMachine',
            config={
                'StdRESTful': {
                    'RainMachine': {
                        'token': 'INSERT_RAINMACHINE_ACCESS_TOKEN',
                        'ip': 'INSERT_RAINMACHINE_IP'}}},
            files=[('bin/user', ['bin/user/rainmachine.py'])]
            )
