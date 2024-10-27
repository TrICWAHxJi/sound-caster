from functools import wraps
import threading
import typer
import pyaudio
import struct
import tomllib
import asyncio


class Device:
    index: str
    label: str
    portaudio: pyaudio.PyAudio

    __running = False

    def __init__(self, index: str, label: str, portaudio: pyaudio.PyAudio):
        self.index = index
        self.label = label
        self.portaudio = portaudio

    async def start(self):
        self.__running = True

        format = getattr(pyaudio, config["pyaudio"]["format"])
        chunk = config["pyaudio"]["chunk"]

        try:
            device_info = self.portaudio.get_device_info_by_index(self.index)
            channels = int(device_info["maxInputChannels"])
            rate = int(device_info["defaultSampleRate"])

            stream = self.portaudio.open(
                format=format,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=self.index,
                frames_per_buffer=chunk,
            )

            reader, writer = await asyncio.open_connection(
                config["server"]["ip"], config["server"]["port"]
            )

            # Send audio configuration
            writer.write(struct.pack("III", channels, 2, rate))
            await writer.drain()

            while self.__running:
                data = stream.read(chunk)
                writer.write(struct.pack("H", len(data)) + data)
                await writer.drain()

            writer.close()
            await writer.wait_closed()
        except asyncio.CancelledError:
            typer.secho("\nServer disconnected!", fg="red", err=True)
        except ConnectionRefusedError:
            typer.secho("\nCannot connect to the server!", fg="red", err=True)
        except ConnectionResetError:
            typer.secho("\nServer disconnected!", fg="red", err=True)
        except ConnectionAbortedError:
            typer.secho("\nServer disconnected!", fg="red", err=True)
        finally:
            stream.stop_stream()
            stream.close()

            self.__running = False

    async def stop(self):
        if not self.__running:
            return

        self.__running = False

        self.portaudio.terminate()

        typer.echo(f"Stopped device '{self.label}'")

    def __repr__(self) -> str:
        return self.label


config: dict = {}
devices: dict[str, Device] = {}


def get_devices(portaudio: pyaudio.PyAudio):
    devices = {}
    for i in range(portaudio.get_device_count()):
        info = portaudio.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0 and i not in devices.keys():
            devices[i] = (
                f"Device {i}: {info['name']} (Channels: {info['maxInputChannels']})"
            )

    return devices


def choose_device(prompt: str):
    portaudio = pyaudio.PyAudio()

    typer.echo("Available audio devices with input channels:")
    available_devices = get_devices(portaudio)
    for index, item in available_devices.items():
        typer.echo(item)

    while True:
        choice = typer.prompt(prompt)
        try:
            index = int(choice)
            if index in available_devices:
                return Device(index, available_devices[index], portaudio)
            else:
                typer.echo("Invalid index. Please choose a valid index.")
        except ValueError:
            typer.echo("Invalid input. Please enter a number.")


def choose_streaming_device(prompt: str) -> Device:
    typer.echo("Streaming devices:")
    for item in devices.values():
        typer.echo(item.label)

    while True:
        choice = typer.prompt(prompt)
        try:
            index = int(choice)
            if index in devices:
                return devices[index]
            else:
                typer.echo("Invalid index. Please choose a valid index.")
        except ValueError:
            typer.echo("Invalid input. Please enter a number.")


async def handle_start():
    device = choose_device("Choose device")

    devices[device.index] = device

    t = threading.Thread(target=lambda: asyncio.run(device.start()))
    t.start()

    typer.echo("Streaming devices:")
    for device in devices.values():
        typer.echo(f"- {device}")


async def handle_stop():
    if len(devices) == 0:
        typer.echo("There are no streaming devices")
        return

    device = choose_streaming_device("Choose device to stop")

    await device.stop()

    devices.pop(device.index, None)

    if len(devices) == 0:
        return

    typer.echo("Streaming devices:")
    for device in devices.values():
        typer.echo(f"- {device}")


async def handle_exit():
    typer.echo("Exiting the application. Goodbye!")

    if len(devices) == 0:
        return

    await asyncio.gather(*[device.stop() for device in devices.values()])


def typer_async(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


@typer_async
async def main(config_path: str = "config.toml"):
    with open(config_path, "rb") as f:
        global config
        config = tomllib.load(f)

    while True:
        command = typer.prompt("Enter command (start, stop, or exit)")
        if command.lower() == "start":
            await handle_start()
        elif command.lower() == "stop":
            await handle_stop()
        elif command.lower() == "exit":
            await handle_exit()
            break
        else:
            typer.echo("Invalid command. Please enter 'start', 'stop' or 'exit'.")


if __name__ == "__main__":
    typer.run(main)
