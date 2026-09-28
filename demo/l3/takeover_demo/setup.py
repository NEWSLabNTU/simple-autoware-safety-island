from glob import glob

from setuptools import setup

PKG = 'takeover_demo'
NODES = [
    'odd_monitor',
    'takeover_hmi',
    'availability_gate',
    'driver_button',
    'hazard_relay',
    'graph_watcher',
    'scenario',
]

setup(
    name=PKG,
    version='0.1.0',
    packages=[PKG],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + PKG]),
        ('share/' + PKG, ['package.xml']),
        ('share/' + PKG + '/launch', glob('launch/*.xml') + glob('launch/*.yaml')),
        ('share/' + PKG + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='aeon',
    description='Host side of the phase-8 L3 takeover demo',
    license='Apache License 2.0',
    entry_points={
        'console_scripts': [f'{n} = {PKG}.{n}:main' for n in NODES],
    },
)
