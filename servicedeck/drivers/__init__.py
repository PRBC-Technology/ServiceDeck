"""Camera control drivers."""

from servicedeck.drivers.http_cgi import HttpCgiDriver
from servicedeck.drivers.visca_ip import ViscaIpDriver

DRIVERS = {
    ViscaIpDriver.protocol_id: ViscaIpDriver,
    HttpCgiDriver.protocol_id: HttpCgiDriver,
}


def open_driver(camera: dict):
    protocol = camera.get("protocol")
    driver_type = DRIVERS.get(protocol)
    if driver_type is None:
        from servicedeck.drivers.base import PtzError

        raise PtzError(f"Unknown camera protocol: {protocol}")
    return driver_type(camera["host"], int(camera["port"]))
