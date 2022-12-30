"""Communication library to talk with IEC 6... power meters."""
import asyncio
from enum import Enum
from functools import partial, reduce
import re
from typing import Optional

from serial_asyncio import SerialTransport, create_serial_connection

UnitType = Optional[str]


class Parity(Enum):
    """The definition of the parity bit."""

    NONE = "N"
    EVEN = "E"
    ODD = "O"


class PowerMeterError(Exception):
    """Exception class for errors depending on the power meter connection."""


class PollingMeterConfiguration:
    """Configurationvalues of a `PollingPowerMeter`."""

    baudrate: int
    max_baudrate: int
    data_bits: int
    stop_bits: int
    parity: Parity

    def __init__(self) -> None:
        """Initialize this."""
        self.port = None
        self.address = None

        self.baudrate = 300
        self.max_baudrate = 1300
        self.data_bits = 7
        self.stop_bits = 1
        self.parity = Parity.EVEN


class PollingMeterIdentification:
    """Information about the type and cpabilities of the metering device."""

    manufacturer: str
    identifiction: str
    max_baudrate: int
    min_delay_ms: int


class ProtocolModeC(asyncio.Protocol):
    """Test class."""

    class State(Enum):
        """Handshake state."""

        INITIALIZED = 1
        REQUEST_SENDING = 2
        REQUEST_SENT = 3
        ACK_SENDING = 4
        ACK_SENT = 5
        COMPLETED = 6

    baudrates: dict = {
        "0": 300,
        "1": 600,
        "2": 1200,
        "3": 2400,
        "4": 4800,
        "5": 9600,
        "6": 19200,
    }

    def __init__(self, config: PollingMeterConfiguration) -> None:
        """Initialize this."""
        super().__init__()
        self.identification = None
        self.datagram = None
        self._config = config
        self.finished = asyncio.Event()
        self._state = ProtocolModeC.State.INITIALIZED
        self._buffer = bytearray(0)
        self._bits = self.calculate_number_of_bits()
        self._transport = None
        self.start_sequence = (
            b"/?!\r\n"
            if config.address is None
            else f"/?{config.address}!\r\n".encode("ASCII")
        )
        self.ack_sequence = "\x060{}0\r\n"

    def connection_made(self, transport: SerialTransport):
        """Handle connected."""
        self._transport = transport
        # print("port opened", transport)
        asyncio.get_event_loop().create_task(ProtocolModeC.send_req(self))

    def data_received(self, data):
        """Handle connected."""
        if (
            self._state is ProtocolModeC.State.ACK_SENDING
            or self._state is ProtocolModeC.State.REQUEST_SENDING
        ):
            return
        # print("data received", repr(data))
        self._buffer += data
        if self._state == ProtocolModeC.State.REQUEST_SENT:
            if self._buffer.endswith(b"\r\n"):
                self.identification = parse_identification(
                    self._buffer.decode("ASCII"), self.decode_baudrate
                )
                # print(f"received identification {self.identification}")
                self._buffer.clear()
                asyncio.get_event_loop().create_task(ProtocolModeC.send_ack(self))
        elif self._state == ProtocolModeC.State.ACK_SENT:
            if self._buffer[:-1].endswith(b"\r\n\x03"):
                self.datagram = bytes(self._buffer)
                # print(f"received datagram {self.datagram}")
                self._state = ProtocolModeC.State.COMPLETED
                self._transport.close()
                self.finished.set()

    async def send_req(self):
        """Send the first request message."""
        self._state = ProtocolModeC.State.REQUEST_SENDING
        self._transport.write(self.start_sequence)
        time_to_transmit = self.calculate_time_to_transmit(
            self._config.baudrate, self.start_sequence
        )
        await asyncio.sleep(time_to_transmit + 0.015)
        self._state = ProtocolModeC.State.REQUEST_SENT

    async def send_ack(self):
        """Send the acknowledgement message."""
        self._state = ProtocolModeC.State.ACK_SENDING
        await asyncio.sleep(0.2)
        rate = self.calculate_baudrate(
            self.identification.max_baudrate, self._config.max_baudrate
        )
        ack = self.ack_sequence.format(rate[0]).encode("ASCII")
        self._transport.write(ack)
        time_to_transmit = self.calculate_time_to_transmit(self._config.baudrate, ack)
        await asyncio.sleep(time_to_transmit + 0.015)

        self._transport.serial.baudrate = rate[1]
        self._state = ProtocolModeC.State.ACK_SENT

    def calculate_time_to_transmit(self, baudrate, message):
        """Calculate the time it needs to transmit a message with the given baudrate."""
        time_to_transmit = 1 / baudrate * self._bits * len(message)
        return time_to_transmit

    def calculate_number_of_bits(self):
        """Calculate the number of bits on the wire."""
        bits = (
            1  # start bit
            + self._config.data_bits
            + self._config.stop_bits
            + (1 if self._config.parity != Parity.NONE else 0)
        )
        return bits

    def decode_baudrate(self, char: str) -> int:
        """Decode max baudrate."""
        if char in ProtocolModeC.baudrates:
            return ProtocolModeC.baudrates[char]
        raise PowerMeterError("Invalid maximum baudrate.", char)

    def calculate_baudrate(self, max_device: int, max_user: int) -> tuple[str, int]:
        """Calculate the maximum baudrate given by device and user."""
        available = list(ProtocolModeC.baudrates.items())
        available.sort(key=lambda v: v[1], reverse=True)
        for i in available:
            if i[1] <= max_device and i[1] <= max_user:
                return i
        return available[-1]


def parse_identification(text: str, decode_baudrate):
    """Parse the device identification message."""
    if len(text) < 7:
        raise PowerMeterError("Identification is too short.", text)
    if len(text) > 23:
        raise PowerMeterError("Identification is too long.", text)
    if text[0] != "/" or text[-1] != "\n" or text[-2] != "\r":
        raise PowerMeterError("Identification has invalid format.", text)
    result: PollingMeterIdentification = PollingMeterIdentification()
    result.manufacturer = text[1:4]
    result.identifiction = text[5:-2]
    result.min_delay_ms = 20 if result.manufacturer[-1:].islower() else 200
    result.max_baudrate = decode_baudrate(text[4:5])

    return result


class PollingPowerMeter:
    """Communication with a power meter which needs a request before sending any data."""

    dataset_regex = re.compile(
        r"^(?P<key>[^(]*)\((?P<value>[^*)]*)(?:\*(?P<unit>[^)]*))?\)$"
    )

    def __init__(self, config: PollingMeterConfiguration) -> None:
        """Initialize this."""
        self.config = config

    async def read_once(
        self, loop: asyncio.AbstractEventLoop
    ) -> dict[str, tuple[str, UnitType]]:
        """Execute one read cycle."""
        try:
            transport, protocol = await create_serial_connection(
                loop,
                partial(ProtocolModeC, self.config),
                url=self.config.port,
                baudrate=self.config.baudrate,
                bytesize=self.config.data_bits,
                parity=self.config.parity.value,
                stopbits=self.config.stop_bits,
            )

            if transport is None:
                raise PowerMeterError("Failed to open COM port")

            await protocol.finished.wait()
            return self.decode_datagram(protocol.identification, protocol.datagram)
        except Exception as err:
            raise PowerMeterError(err) from err

    def decode_datagram(self, ident: PollingMeterIdentification, data: bytes):
        """Convert the retrieved data into the desired format."""
        self.verify_data(data)
        result = dict[str, tuple[str, UnitType]]()
        result["!manufacturer"] = (ident.manufacturer, None)
        result["!identification"] = (ident.identifiction, None)
        start_index = 1 if data[0:1] == b"\x02" else 0
        text = data[start_index:-5].decode("ASCII")
        lines = text.splitlines()
        for line in lines:
            match = PollingPowerMeter.dataset_regex.match(line)
            if not match:
                raise PowerMeterError("Invalid data row.", line)
            result[match.group("key")] = (match.group("value"), match.group("unit"))

        return result

    def verify_data(self, data: bytes) -> None:
        """Check consistency of datagram."""
        if len(data) < 5:
            raise PowerMeterError("Data is too short.", data)
        if data[0:1] != b"\x02" and len(data) > 5:
            raise PowerMeterError("Invalid start character.", data)
        if data[-5:-1] != b"!\r\n\x03":
            raise PowerMeterError("Invalid dataset termination.", data)
        start_index = 1 if data[0:1] == b"\x02" else 0
        checksum = reduce(lambda x, y: x ^ y, data[start_index:-1], 0)
        if checksum != int(data[-1]):
            raise PowerMeterError("Corrupted data. Wrong BCC", data)
